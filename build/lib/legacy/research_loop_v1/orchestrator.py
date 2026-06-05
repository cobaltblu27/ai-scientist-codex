from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import make_runner
from .config import ACTIONS, ResearchConfig, parse_args
from .criteria import select_node
from .dispatcher import FifoDispatcher, NodeTask
from .executor import execute_baseline, execute_node
from .governance import bootstrap, update_status
from .handoff import append_approved_handoff, artifact_snapshot, record_validation, run_validator, write_gate_decision
from .journal import Journal, utc_now, write_json
from .manifests import ManifestError, copy_workspace_artifacts, materialize_manifest, validate_manifest
from .prompts import build_prompt, write_prompt


def planned_actions(config: ResearchConfig) -> list[str]:
    base = ["draft"]
    if config.max_debug_attempts:
        base.append("debug")
    if config.max_improve_attempts:
        base.append("improve")
    if config.strictness_mode in {"scientist", "researcher", "balanced", "engineer"} and config.max_tuning_attempts:
        base.append("tuning")
    if config.strictness_mode in {"scientist", "researcher", "balanced"} and config.max_ablation_attempts:
        base.append("ablation")
    return base[: config.max_nodes]


def _baseline_command(config: ResearchConfig) -> str:
    return config.baseline_command


def _node_id(index: int, action: str) -> str:
    return f"{index:03d}-{action}"


def run_node(config: ResearchConfig, runner, idea: dict[str, Any], task: NodeTask, journal: Journal) -> dict[str, Any]:
    node_dir = config.run_dir / "nodes" / task.node_id
    workspace = node_dir / "workspace"
    node_dir.mkdir(parents=True, exist_ok=True)
    node_meta = {"node_id": task.node_id, "action": task.action, "parent_node_id": task.parent_node_id, "strictness_mode": config.strictness_mode, "status": "running", "created_at": utc_now()}
    write_json(node_dir / "node.json", node_meta)
    prompt = build_prompt(config, task.action, task.node_id, task.parent_node_id, idea)
    write_prompt(node_dir / "prompt.json", prompt)
    try:
        manifest = runner.run(prompt, config)
        write_json(node_dir / "agent-output.json", {"manifest": manifest, "runner": config.agent_runner})
        accepted = validate_manifest(manifest, workspace, config.metric_key, config.metric_direction)
        materialize_manifest(accepted, workspace, node_dir / "manifest-validation.json")
    except (ManifestError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        write_json(node_dir / "manifest-validation.json", {"accepted": False, "reason": str(exc)})
        node_meta.update({"status": "blocked_manifest", "completed_at": utc_now()})
        write_json(node_dir / "node.json", node_meta)
        journal.record("node_blocked_manifest", node_id=task.node_id, reason=str(exc))
        return {"node_id": task.node_id, "status": "blocked_manifest", "reason": str(exc)}
    result = execute_node(accepted["command"], workspace, node_dir, config.target_repo, config.node_timeout_sec, config.resources)
    copy_workspace_artifacts(workspace, node_dir)
    status = "completed" if result["return_code"] == 0 and result["runtime_mutation_passed"] else "blocked_runtime_mutation" if not result["runtime_mutation_passed"] else "failed"
    node_meta.update({"status": status, "return_code": result["return_code"], "completed_at": utc_now()})
    write_json(node_dir / "node.json", node_meta)
    journal.record("node_finished", node_id=task.node_id, status=status, return_code=result["return_code"])
    return {"node_id": task.node_id, "status": status}


def finalize(config: ResearchConfig, selection: dict[str, Any], journal: Journal) -> int:
    evidence_code, evidence_output, evidence_cmd = run_validator(Path(__file__).resolve().parents[1], config.target_repo, config.run_id, "evidence")
    write_json(config.run_dir / "evidence-validation-output.json", {"command": evidence_cmd, "exit_code": evidence_code, "output": evidence_output})
    if evidence_code != 0 or not selection.get("selected_node"):
        reason = evidence_output.strip() or selection.get("reason", "evidence validation failed")
        snapshot = artifact_snapshot(config.run_dir)
        record_validation(config.run_dir, "research_to_review", "evidence", evidence_code or 1, selection.get("selected_node"), config.metric_key, config.metric_direction, snapshot)
        update_status(config.run_dir, status="blocked", blocked_reason=reason, completed_at=utc_now())
        journal.record("handoff_blocked", reason=reason)
        return evidence_code or 1

    snapshot = artifact_snapshot(config.run_dir)
    validation = record_validation(config.run_dir, "research_to_review", "evidence", 0, selection.get("selected_node"), config.metric_key, config.metric_direction, snapshot)
    append_approved_handoff(config.run_dir, validation)
    write_gate_decision(config.run_dir, validation, evidence_cmd, None)
    final_code, final_output, final_cmd = run_validator(Path(__file__).resolve().parents[1], config.target_repo, config.run_id, "final")
    write_json(config.run_dir / "final-validation-output.json", {"command": final_cmd, "exit_code": final_code, "output": final_output})
    if final_code == 0:
        write_gate_decision(config.run_dir, validation, evidence_cmd, final_cmd)
        update_status(config.run_dir, status="research_to_review_ready", completed_at=utc_now())
        journal.record("handoff_approved", selected_node=selection.get("selected_node"))
        return 0
    update_status(config.run_dir, status="blocked", blocked_reason="final validator failed", final_validation_output=final_output, completed_at=utc_now())
    journal.record("final_validation_failed", output=final_output)
    return final_code or 1


def run(config: ResearchConfig) -> int:
    idea = bootstrap(config)
    journal = Journal(config.run_dir)
    journal.record("run_started", run_id=config.run_id)
    baseline_dir = config.run_dir / "baseline"
    execute_baseline(_baseline_command(config), baseline_dir, config.node_timeout_sec, config.metric_key, config.target_repo, config.resources)
    journal.record("baseline_finished")
    runner = make_runner(config.agent_runner)
    actions = planned_actions(config)
    tasks = [
        NodeTask(
            _node_id(i + 1, action),
            action,
            None if i == 0 else _node_id(i, actions[i - 1]),
            gpus=0,
            cpu_cores=1 if config.resources.cpu_cores is not None else 0,
            memory_mb=min(512, config.resources.memory_mb) if config.resources.memory_mb is not None else 0,
        )
        for i, action in enumerate(actions)
    ]
    dispatcher = FifoDispatcher(config.run_dir / "dispatcher-events.jsonl", config.max_parallel, config.resources.max_gpus, config.resources.cpu_cores, config.resources.memory_mb)
    dispatcher.enqueue_many(tasks)
    dispatcher.run(lambda task: run_node(config, runner, idea, task, journal))
    selection = select_node(config.run_dir, config.strictness_mode, config.metric_key, config.metric_direction, config.success_threshold)
    write_json(config.run_dir / "selection.json", selection)
    return finalize(config, selection, journal)


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    return run(config)

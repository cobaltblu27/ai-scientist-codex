#!/usr/bin/env python3
"""Agent-facing helper CLI for AI Scientist research-loop state."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ai_scientist_state import (
    append_journal_event,
    audit_block_reason,
    block_for_manual_recovery,
    atomic_write_json,
    clear_active_run,
    config_path,
    data_hash,
    has_stop_release_evidence,
    journal_has_event,
    journal_path,
    load_active_run,
    load_json_if_exists,
    load_loop_state,
    mutate_loop_state,
    node_dir,
    node_json_path,
    run_dir,
    selection_path,
    set_active_run,
    start_phase,
    utc_now,
    validate_active_run_contract,
)
from ideation_state import (
    IdeationStateError,
    cancel_ideation,
    cancel_intent,
    complete_ideation,
    complete_intent,
    current_config,
    cursor_for_state,
    exhaust_idea,
    exhaust_ideation,
    finalize_idea,
    finalize_ranking,
    record_critic,
    record_draft,
    record_semantic_scholar_search,
    reject_idea,
    resume_ideation,
    start_ideation,
    start_intent,
    start_revision,
)

MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
NODE_STATUSES = {"planned", "implementing", "running", "buggy", "repairing", "candidate", "validating", "accepted", "invalid", "rejected"}
SUBAGENT_STATUSES = {
    "planned",
    "running",
    "blocked_on_resource",
    "completed_unintegrated",
    "failed_unreviewed",
    "integrated",
    "rejected_with_reason",
    "abandoned_with_reason",
}


class CliError(Exception):
    pass


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "json_file", None):
        value = json.loads(Path(args.json_file).read_text())
    elif getattr(args, "json", None):
        value = json.loads(args.json)
    else:
        value = {}
    if not isinstance(value, dict):
        raise CliError("payload must be a JSON object")
    return value


def target_repo(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "target_repo", None) or Path.cwd()).resolve()


def active_run(target: Path, run_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
    if run_id:
        state = load_loop_state(target, run_id)
        if state:
            block_reason = audit_block_reason(target, run_id, state)
            if block_reason:
                if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                    block_for_manual_recovery(target, run_id, state, block_reason)
                raise CliError(block_reason)
        return run_id, state
    active = load_active_run(target)
    if not isinstance(active, dict) or not isinstance(active.get("run_id"), str):
        raise CliError("no active AI Scientist run; pass --run-id only for recovery/test paths")
    active_reason = validate_active_run_contract(active)
    if active_reason:
        raise CliError(f"active-run.json invalid: {active_reason}")
    rid = active["run_id"]
    state = load_loop_state(target, rid)
    if state:
        block_reason = audit_block_reason(target, rid, state)
        if block_reason:
            if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                block_for_manual_recovery(target, rid, state, block_reason)
            raise CliError(block_reason)
    return rid, state


def response(status: str, **fields: Any) -> int:
    sys.stdout.write(json.dumps({"status": status, **fields}, indent=2, sort_keys=True) + "\n")
    return 0 if status == "ok" else 1


def default_config(target: Path, run_id: str, strictness_mode: str, payload: dict[str, Any]) -> dict[str, Any]:
    if strictness_mode not in MODES:
        raise CliError(f"invalid strictness mode: {strictness_mode}")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "target_repo": str(target),
        "strictness_mode": strictness_mode,
        "api_budgets": payload.get("api_budgets", {"semantic_scholar": {"max_calls": 100}}),
        "workspace": payload.get("workspace", {"mode": "copy", "baseline_workspace": f".ai-scientist/runs/{run_id}/baseline-workspace"}),
        "dependency_plan": payload.get("dependency_plan", {"mode": "frozen", "planned_dependencies": []}),
        "benchmark_contract": payload.get("benchmark_contract", {"version": "v1", "command": payload.get("benchmark_command")}),
        "resources": payload.get("resources", {"gpu": {"mode": "single_full_device_when_requested"}}),
        "selection": payload.get("selection", {"good_enough_score_threshold": 75}),
        "created_at": utc_now(),
    }


def cmd_research_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    payload = load_payload(args)
    run_id = args.run_id
    initial_state = {
        "orchestrator": {
            "role": "main_codex_session",
            "iteration": 0,
            "next_action": "setup",
            "next_action_details": {"reason": "research run started"},
            "last_checkpoint_at": utc_now(),
        },
        "workspace_plan_status": "pending",
        "dependency_plan_status": "pending",
        "baseline_status": "pending",
        "selected_node": None,
        "node_queue": [],
        "nodes": {},
        "subagents": {},
        "resources": {},
        "selection": {"status": "pending", "selected_node": None},
    }
    initial_state.update(payload.get("state", {}))
    state = start_phase(target, run_id, "research", initial_state)
    cfg = default_config(target, run_id, args.strictness_mode, payload)
    atomic_write_json(config_path(target, run_id), cfg)
    append_journal_event(target, run_id, "state_transition", details={"command": "research start", "state_hash": data_hash(state)})
    return response("ok", run_id=run_id, state_path=str(run_dir(target, run_id) / "loop-state.json"), config_path=str(config_path(target, run_id)))


def cmd_research_resume(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.setdefault("state", {})
    orchestrator = phase_state.setdefault("orchestrator", {})
    next_action = orchestrator.get("next_action")
    if not next_action:
        raise CliError("active research is missing orchestrator.next_action")
    append_journal_event(target, run_id, "state_transition", details={"command": "research resume", "next_action": next_action})
    set_active_run(target, run_id, str(state.get("phase") or "research"), "active")
    return response("ok", run_id=run_id, next_action=next_action, next_action_details=orchestrator.get("next_action_details", {}))


def cmd_research_set_next_action(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)
    details = payload.get("details", {})
    if args.reason:
        details = {**details, "reason": args.reason}
    if not isinstance(details, dict) or not details.get("reason"):
        raise CliError("next_action details require a non-empty reason")

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        orchestrator = phase_state.setdefault("orchestrator", {})
        orchestrator["next_action"] = args.lane
        orchestrator["next_action_details"] = details
        orchestrator["last_checkpoint_at"] = utc_now()
        if args.node_id:
            orchestrator["current_node"] = args.node_id

    updated = mutate_loop_state(target, run_id, "state_transition", {"command": "research set-next-action", "lane": args.lane, "details": details}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, next_action=updated["state"]["orchestrator"]["next_action"])


def cmd_research_checkpoint(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        phase_state.update(payload.get("state", {}))
        orchestrator = phase_state.setdefault("orchestrator", {})
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "research checkpoint", "payload": payload}, mutator)
    return response("ok", run_id=run_id)


def cmd_research_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    audit = load_payload(args)
    if audit.get("passed") is not True:
        raise CliError("completion audit must include passed=true")

    def mutator(state: dict[str, Any]) -> None:
        state["active"] = False
        state["phase_status"] = "complete"
        state["completed_at"] = utc_now()
        state["completion_audit"] = audit

    mutate_loop_state(target, run_id, "state_transition", {"command": "research complete"}, mutator)
    set_active_run(target, run_id, "research", "validating")
    return response("ok", run_id=run_id, active_status="validating")


def cmd_research_cancel(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    def mutator(state: dict[str, Any]) -> None:
        state["active"] = False
        state["phase_status"] = "cancelled"
        state["run_outcome"] = "cancelled"
        state["cancellation_reason"] = args.reason
        state["completed_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "research cancel", "reason": args.reason}, mutator)
    clear_active_run(target, run_id)
    return response("ok", run_id=run_id, phase_status="cancelled")


def read_node(target: Path, run_id: str, node_id: str) -> dict[str, Any]:
    value = load_json_if_exists(node_json_path(target, run_id, node_id))
    return value if isinstance(value, dict) else {"node_id": node_id, "trials": []}


def write_node(target: Path, run_id: str, node_id: str, node: dict[str, Any]) -> None:
    node["node_id"] = node_id
    atomic_write_json(node_json_path(target, run_id, node_id), node)


def cmd_node_transition(args: argparse.Namespace) -> int:
    if args.status not in NODE_STATUSES:
        raise CliError(f"invalid node status: {args.status}")
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)
    node_payload = payload.get("node", payload)
    node = read_node(target, run_id, args.node_id)
    node.update(node_payload if isinstance(node_payload, dict) else {})
    node["status"] = args.status
    write_node(target, run_id, args.node_id, node)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        nodes = phase_state.setdefault("nodes", {})
        current = nodes.setdefault(args.node_id, {})
        current.update({"status": args.status, "updated_at": utc_now()})
        if args.reason:
            key = "rejection_reason" if args.status in {"rejected", "invalid"} else "reason"
            current[key] = args.reason
        if args.status == "accepted":
            phase_state.setdefault("selection", {}).setdefault("status", "pending")

    mutate_loop_state(target, run_id, "state_transition", {"command": "node transition", "status": args.status, "reason": args.reason}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, node_id=args.node_id, node_status=args.status, node_path=str(node_json_path(target, run_id, args.node_id)))


def cmd_node_create_workspace(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    baseline = run_dir(target, run_id) / "baseline-workspace"
    if not baseline.exists():
        raise CliError(f"missing baseline workspace: {baseline}")
    workspace = node_dir(target, run_id, args.node_id) / "workspace"
    if workspace.exists():
        raise CliError(f"node workspace already exists: {workspace}")
    shutil.copytree(baseline, workspace, symlinks=True)
    payload = {"workspace_path": str(workspace), "status": "planned"}
    args.status = "planned"
    args.json = json.dumps({"node": payload})
    args.json_file = None
    args.reason = args.reason or "node workspace created"
    return cmd_node_transition(args)


def cmd_subagent_update(args: argparse.Namespace) -> int:
    if args.status not in SUBAGENT_STATUSES:
        raise CliError(f"invalid subagent status: {args.status}")
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        subagents = phase_state.setdefault("subagents", {})
        current = subagents.setdefault(args.subagent_id, {})
        current.update(payload)
        current["status"] = args.status
        current["updated_at"] = utc_now()
        if args.node_id:
            current["node_id"] = args.node_id

    mutate_loop_state(target, run_id, "subagent_event", {"command": "subagent update", "status": args.status}, mutator, node_id=args.node_id, subagent_id=args.subagent_id)
    return response("ok", run_id=run_id, subagent_id=args.subagent_id, subagent_status=args.status)


def cmd_selection_finalize(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    payload = load_payload(args)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    selected = payload.get("selected_node") or args.selected_node
    if not isinstance(selected, str) or not selected:
        raise CliError("selected_node is required")
    if not isinstance(nodes.get(selected), dict) or nodes[selected].get("status") != "accepted":
        raise CliError("selected node must be accepted in loop-state.json")
    accepted_nodes = [node_id for node_id, node in nodes.items() if isinstance(node, dict) and node.get("status") == "accepted"]
    ranked = payload.get("ranked_nodes") or [{"node_id": node_id} for node_id in accepted_nodes]
    ranked_ids = [item.get("node_id") for item in ranked if isinstance(item, dict)]
    missing = sorted(set(accepted_nodes) - set(ranked_ids))
    if missing:
        raise CliError(f"selection is missing accepted nodes: {', '.join(missing)}")
    selection = {
        "schema_version": 1,
        "run_id": run_id,
        "selection_status": "final",
        "provisional": False,
        "selected_node": selected,
        "ranked_nodes": ranked,
        "manual_override": payload.get("manual_override"),
        "rationale": payload.get("rationale"),
        "updated_at": utc_now(),
    }
    atomic_write_json(selection_path(target, run_id), selection)

    def mutator(new_state: dict[str, Any]) -> None:
        new_phase_state = new_state.setdefault("state", {})
        new_phase_state["selected_node"] = selected
        new_phase_state["selection"] = {"status": "final", "selected_node": selected, "selection_ref": str(selection_path(target, run_id))}

    mutate_loop_state(target, run_id, "selection", {"command": "selection finalize", "selected_node": selected}, mutator, node_id=selected)
    return response("ok", run_id=run_id, selected_node=selected, selection_path=str(selection_path(target, run_id)))


def cmd_validation_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    append_journal_event(target, run_id, "validation", details={"gate": args.gate, "exit_code": args.exit_code, "validator_exit_code": args.exit_code, "command": args.command})
    return response("ok", run_id=run_id, gate=args.gate, exit_code=args.exit_code)


def cmd_handoff_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    approved = args.approved
    append_journal_event(
        target,
        run_id,
        "handoff",
        details={"gate": args.gate, "approved": approved, "exit_code": args.exit_code, "validator_exit_code": args.exit_code, "reason": args.reason},
    )
    if approved and state and state.get("phase_status") == "complete" and has_stop_release_evidence(target, run_id, str(state.get("phase") or "research")):
        clear_active_run(target, run_id)
    return response("ok", run_id=run_id, gate=args.gate, approved=approved)


def require_ideation_run(args: argparse.Namespace) -> tuple[Path, str]:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if state and state.get("phase") != "ideation":
        raise CliError(f"active run is not ideation: {state.get('phase')}")
    return target, run_id


def ideation_response(target: Path, run_id: str, **extra: Any) -> int:
    state = load_loop_state(target, run_id)
    cfg = current_config(target, run_id) if state and state.get("phase") == "ideation" else {}
    cursor = cursor_for_state(state, cfg) if isinstance(state, dict) and state.get("phase") == "ideation" else {}
    return response("ok", run_id=run_id, phase_status=state.get("phase_status") if isinstance(state, dict) else None, **cursor, **extra)


def cmd_ideation_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    state = start_ideation(
        target,
        args.run_id,
        args.prompt,
        mode=args.strictness_mode,
        num_ideas_required=args.num_ideas,
        min_candidates_required=args.min_candidates,
        reflection_budget=args.reflection_budget,
    )
    cfg = current_config(target, args.run_id)
    cursor = cursor_for_state(state, cfg)
    return response("ok", run_id=args.run_id, state_path=str(run_dir(target, args.run_id) / "loop-state.json"), config_path=str(config_path(target, args.run_id)), **cursor)


def cmd_ideation_resume(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    result = resume_ideation(target, run_id, prompt=args.prompt)
    return response("ok", **result)


def cmd_ideation_cancel(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    cancel_ideation(target, run_id, args.reason)
    return ideation_response(target, run_id)


def cmd_ideation_complete(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    complete_ideation(target, run_id, budget_exhausted=args.budget_exhausted)
    return ideation_response(target, run_id)


def cmd_ideation_exhaust(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    exhaust_ideation(target, run_id)
    return ideation_response(target, run_id)


def cmd_ideation_rank_finalize(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    finalize_ranking(target, run_id, payload)
    return ideation_response(target, run_id)


def cmd_ideation_intent_start(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    intent = start_intent(target, run_id, args.role, idea_id=args.idea_id)
    return ideation_response(target, run_id, intent=intent)


def cmd_ideation_intent_complete(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    complete_intent(target, run_id, payload)
    return ideation_response(target, run_id)


def cmd_ideation_intent_cancel(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    cancel_intent(target, run_id, args.reason)
    return ideation_response(target, run_id)


def cmd_idea_draft(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    idea_payload = payload.get("idea") if isinstance(payload.get("idea"), dict) else payload
    record_draft(target, run_id, idea_payload, idea_id=args.idea_id)
    return ideation_response(target, run_id)


def cmd_idea_revise_start(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    start_revision(target, run_id, args.idea_id, args.reason)
    return ideation_response(target, run_id)


def cmd_idea_critic_record(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    critic_payload = payload.get("critic") if isinstance(payload.get("critic"), dict) else payload
    record_critic(target, run_id, critic_payload, idea_id=args.idea_id)
    return ideation_response(target, run_id)


def cmd_idea_search_semantic_scholar(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    if not payload and not args.query:
        raise CliError("search-semantic-scholar requires --query or a JSON evidence payload")
    record_semantic_scholar_search(
        target,
        run_id,
        idea_id=args.idea_id,
        query=args.query,
        evidence_payload=payload or None,
        limit=args.limit,
    )
    return ideation_response(target, run_id)


def cmd_idea_finalize(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    finalize_idea(target, run_id, idea_id=args.idea_id)
    return ideation_response(target, run_id)


def cmd_idea_reject(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    reject_idea(target, run_id, idea_id=args.idea_id, reason=args.reason)
    return ideation_response(target, run_id)


def cmd_idea_exhaust(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    exhaust_idea(target, run_id, idea_id=args.idea_id, reason=args.reason)
    return ideation_response(target, run_id)


def copy_ignore(_dir: str, names: list[str]) -> set[str]:
    ignored = {".git", ".ai-scientist", "__pycache__", ".pytest_cache", ".mypy_cache"}
    return {name for name in names if name in ignored}


def cmd_workspace_init(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    source = Path(args.source).resolve()
    baseline = run_dir(target, run_id) / "baseline-workspace"
    if baseline.exists():
        raise CliError(f"baseline workspace already exists: {baseline}")
    shutil.copytree(source, baseline, symlinks=True, ignore=copy_ignore)
    cfg = load_json_if_exists(config_path(target, run_id))
    if isinstance(cfg, dict):
        cfg.setdefault("workspace", {})["baseline_workspace"] = str(baseline)
        atomic_write_json(config_path(target, run_id), cfg)

    def mutator(state: dict[str, Any]) -> None:
        state.setdefault("state", {})["workspace_plan_status"] = "complete"

    mutate_loop_state(target, run_id, "workspace", {"command": "workspace init", "source": str(source), "baseline_workspace": str(baseline)}, mutator)
    return response("ok", run_id=run_id, baseline_workspace=str(baseline))


def cmd_resource_run(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise CliError("resource run requires a command after --")
    cwd = Path(args.cwd).resolve() if args.cwd else target
    trial_dir = node_dir(target, run_id, args.node_id) / "trials" / args.trial_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = trial_dir / "stdout.log"
    stderr_path = trial_dir / "stderr.log"
    command_ref = trial_dir / "command.json"
    env = os.environ.copy()
    env_updates = json.loads(args.env_json) if args.env_json else {}
    if not isinstance(env_updates, dict):
        raise CliError("--env-json must be an object")
    env.update({str(key): str(value) for key, value in env_updates.items()})
    env_record = {str(key): str(value) for key, value in env_updates.items()}
    lease_id = None
    lease_path: Path | None = None
    if args.gpu:
        resource_dir = run_dir(target, run_id) / "resources"
        resource_dir.mkdir(parents=True, exist_ok=True)
        lease_id = f"gpu-0-{os.getpid()}-{args.node_id}-{args.trial_id}"
        lease_path = resource_dir / "gpu-0.lock"
        lease_payload = {"lease_id": lease_id, "pid": os.getpid(), "node_id": args.node_id, "trial_id": args.trial_id, "created_at": utc_now()}
        try:
            fd = os.open(lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise CliError(f"gpu resource busy: {lease_path}") from exc
        with os.fdopen(fd, "w") as handle:
            json.dump(lease_payload, handle, sort_keys=True)
            handle.write("\n")
        env.setdefault("CUDA_VISIBLE_DEVICES", "0")
        env_record.setdefault("CUDA_VISIBLE_DEVICES", env["CUDA_VISIBLE_DEVICES"])
    command_spec = {
        "argv": command,
        "cwd": str(cwd),
        "env": {key: env_record[key] for key in sorted(env_record)},
        "gpu_requested": args.gpu,
        "resource_lease_id": lease_id,
        "started_at": utc_now(),
    }
    command_spec["command_spec_hash"] = data_hash(command_spec)
    atomic_write_json(command_ref, command_spec)
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    finally:
        if lease_path is not None:
            try:
                lease_path.unlink()
            except FileNotFoundError:
                pass
    stdout_path.write_text(proc.stdout)
    stderr_path.write_text(proc.stderr)
    command_spec.update({"completed_at": utc_now(), "exit_code": proc.returncode, "stdout": str(stdout_path), "stderr": str(stderr_path)})
    atomic_write_json(command_ref, command_spec)
    metrics: dict[str, Any] | None = None
    if args.metrics_json:
        metrics = json.loads(args.metrics_json)
        metrics_source = "inline_metrics_json"
    elif args.metrics_path and Path(args.metrics_path).exists():
        metrics_value = json.loads(Path(args.metrics_path).read_text())
        if isinstance(metrics_value, dict):
            metrics = metrics_value
        metrics_source = str(args.metrics_path)
    else:
        metrics_source = None
    node = read_node(target, run_id, args.node_id)
    trials = node.setdefault("trials", [])
    trial_record = {
        "trial_id": args.trial_id,
        "purpose": args.purpose,
        "status": "completed" if proc.returncode == 0 else "failed",
        "command_ref": str(command_ref),
        "metrics": metrics,
        "metrics_ref": args.metrics_path,
        "metrics_source": metrics_source,
        "resource_lease_id": lease_id,
        "seed": args.seed,
        "started_at": command_spec["started_at"],
        "ended_at": command_spec["completed_at"],
        "benchmark_contract_version": args.benchmark_contract_version,
        "notes": args.notes,
    }
    trials.append({key: value for key, value in trial_record.items() if value is not None})
    write_node(target, run_id, args.node_id, node)
    append_journal_event(target, run_id, "resource_event", node_id=args.node_id, resource_id=lease_id, details={"command": "resource run", "trial_id": args.trial_id, "exit_code": proc.returncode, "gpu_requested": args.gpu, "resource_lease_id": lease_id, "command_spec_hash": command_spec["command_spec_hash"]})
    return response("ok" if proc.returncode == 0 else "error", run_id=run_id, node_id=args.node_id, trial_id=args.trial_id, exit_code=proc.returncode, command_ref=str(command_ref))


def add_json_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", help="Inline JSON object payload.")
    parser.add_argument("--json-file", type=Path, help="Path to JSON object payload.")
    parser.add_argument("--path", dest="json_file", type=Path, help="Alias for --json-file; useful for oversized payloads.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, help="Target repository. Defaults to current working directory.")
    sub = parser.add_subparsers(dest="area", required=True)

    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="command", required=True)
    start = research_sub.add_parser("start")
    start.add_argument("--run-id", required=True)
    start.add_argument("--strictness-mode", default="scientist")
    add_json_args(start)
    start.set_defaults(func=cmd_research_start)
    resume = research_sub.add_parser("resume")
    resume.add_argument("--run-id")
    resume.set_defaults(func=cmd_research_resume)
    checkpoint = research_sub.add_parser("checkpoint")
    checkpoint.add_argument("--run-id")
    add_json_args(checkpoint)
    checkpoint.set_defaults(func=cmd_research_checkpoint)
    next_action = research_sub.add_parser("set-next-action")
    next_action.add_argument("--run-id")
    next_action.add_argument("--lane", required=True)
    next_action.add_argument("--reason")
    next_action.add_argument("--node-id")
    add_json_args(next_action)
    next_action.set_defaults(func=cmd_research_set_next_action)
    complete = research_sub.add_parser("complete")
    complete.add_argument("--run-id")
    add_json_args(complete)
    complete.set_defaults(func=cmd_research_complete)
    cancel = research_sub.add_parser("cancel")
    cancel.add_argument("--run-id")
    cancel.add_argument("--reason", required=True)
    cancel.set_defaults(func=cmd_research_cancel)

    ideation = sub.add_parser("ideation")
    ideation_sub = ideation.add_subparsers(dest="command", required=True)
    ideation_start = ideation_sub.add_parser("start")
    ideation_start.add_argument("--run-id", required=True)
    ideation_start.add_argument("--prompt", required=True)
    ideation_start.add_argument("--strictness-mode")
    ideation_start.add_argument("--num-ideas", type=int)
    ideation_start.add_argument("--min-candidates", type=int)
    ideation_start.add_argument("--reflection-budget", type=int)
    ideation_start.set_defaults(func=cmd_ideation_start)
    ideation_resume = ideation_sub.add_parser("resume")
    ideation_resume.add_argument("--run-id")
    ideation_resume.add_argument("--prompt", action="store_true")
    ideation_resume.set_defaults(func=cmd_ideation_resume)
    ideation_cancel = ideation_sub.add_parser("cancel")
    ideation_cancel.add_argument("--run-id")
    ideation_cancel.add_argument("--reason", required=True)
    ideation_cancel.set_defaults(func=cmd_ideation_cancel)
    ideation_complete = ideation_sub.add_parser("complete")
    ideation_complete.add_argument("--run-id")
    ideation_complete.add_argument("--budget-exhausted", action="store_true")
    ideation_complete.set_defaults(func=cmd_ideation_complete)
    ideation_exhaust = ideation_sub.add_parser("exhaust")
    ideation_exhaust.add_argument("--run-id")
    ideation_exhaust.set_defaults(func=cmd_ideation_exhaust)
    ideation_rank = ideation_sub.add_parser("rank-finalize")
    ideation_rank.add_argument("--run-id")
    add_json_args(ideation_rank)
    ideation_rank.set_defaults(func=cmd_ideation_rank_finalize)
    ideation_intent = ideation_sub.add_parser("intent")
    ideation_intent_sub = ideation_intent.add_subparsers(dest="intent_command", required=True)
    intent_start = ideation_intent_sub.add_parser("start")
    intent_start.add_argument("--run-id")
    intent_start.add_argument("--role", required=True, choices=sorted({"generator", "critic", "ranker"}))
    intent_start.add_argument("--idea-id")
    intent_start.set_defaults(func=cmd_ideation_intent_start)
    intent_complete = ideation_intent_sub.add_parser("complete")
    intent_complete.add_argument("--run-id")
    add_json_args(intent_complete)
    intent_complete.set_defaults(func=cmd_ideation_intent_complete)
    intent_cancel = ideation_intent_sub.add_parser("cancel")
    intent_cancel.add_argument("--run-id")
    intent_cancel.add_argument("--reason", required=True)
    intent_cancel.set_defaults(func=cmd_ideation_intent_cancel)

    idea = sub.add_parser("idea")
    idea_sub = idea.add_subparsers(dest="command", required=True)
    idea_draft = idea_sub.add_parser("draft")
    idea_draft.add_argument("--run-id")
    idea_draft.add_argument("--idea-id")
    add_json_args(idea_draft)
    idea_draft.set_defaults(func=cmd_idea_draft)
    idea_revise = idea_sub.add_parser("revise-start")
    idea_revise.add_argument("--run-id")
    idea_revise.add_argument("--idea-id", required=True)
    idea_revise.add_argument("--reason")
    idea_revise.set_defaults(func=cmd_idea_revise_start)
    idea_critic = idea_sub.add_parser("critic-record")
    idea_critic.add_argument("--run-id")
    idea_critic.add_argument("--idea-id")
    add_json_args(idea_critic)
    idea_critic.set_defaults(func=cmd_idea_critic_record)
    idea_search = idea_sub.add_parser("search-semantic-scholar")
    idea_search.add_argument("--run-id")
    idea_search.add_argument("--idea-id")
    idea_search.add_argument("--query")
    idea_search.add_argument("--limit", type=int, default=10)
    add_json_args(idea_search)
    idea_search.set_defaults(func=cmd_idea_search_semantic_scholar)
    idea_finalize = idea_sub.add_parser("finalize")
    idea_finalize.add_argument("--run-id")
    idea_finalize.add_argument("--idea-id")
    idea_finalize.set_defaults(func=cmd_idea_finalize)
    idea_reject = idea_sub.add_parser("reject")
    idea_reject.add_argument("--run-id")
    idea_reject.add_argument("--idea-id")
    idea_reject.add_argument("--reason", required=True)
    idea_reject.set_defaults(func=cmd_idea_reject)
    idea_exhaust = idea_sub.add_parser("exhaust")
    idea_exhaust.add_argument("--run-id")
    idea_exhaust.add_argument("--idea-id")
    idea_exhaust.add_argument("--reason", default="reflection_budget_exhausted")
    idea_exhaust.set_defaults(func=cmd_idea_exhaust)

    node = sub.add_parser("node")
    node_sub = node.add_subparsers(dest="command", required=True)
    transition = node_sub.add_parser("transition")
    transition.add_argument("--run-id")
    transition.add_argument("--node-id", required=True)
    transition.add_argument("--status", required=True)
    transition.add_argument("--reason")
    add_json_args(transition)
    transition.set_defaults(func=cmd_node_transition)
    create_workspace = node_sub.add_parser("create-workspace")
    create_workspace.add_argument("--run-id")
    create_workspace.add_argument("--node-id", required=True)
    create_workspace.add_argument("--reason")
    create_workspace.set_defaults(func=cmd_node_create_workspace)

    subagent = sub.add_parser("subagent")
    subagent_sub = subagent.add_subparsers(dest="command", required=True)
    update = subagent_sub.add_parser("update")
    update.add_argument("--run-id")
    update.add_argument("--subagent-id", required=True)
    update.add_argument("--status", required=True)
    update.add_argument("--node-id")
    add_json_args(update)
    update.set_defaults(func=cmd_subagent_update)

    selection = sub.add_parser("selection")
    selection_sub = selection.add_subparsers(dest="command", required=True)
    finalize = selection_sub.add_parser("finalize")
    finalize.add_argument("--run-id")
    finalize.add_argument("--selected-node")
    add_json_args(finalize)
    finalize.set_defaults(func=cmd_selection_finalize)

    validation = sub.add_parser("validation")
    validation_sub = validation.add_subparsers(dest="command", required=True)
    validation_record = validation_sub.add_parser("record")
    validation_record.add_argument("--run-id")
    validation_record.add_argument("--gate", required=True)
    validation_record.add_argument("--exit-code", type=int, required=True)
    validation_record.add_argument("--command")
    validation_record.set_defaults(func=cmd_validation_record)

    handoff = sub.add_parser("handoff")
    handoff_sub = handoff.add_subparsers(dest="command", required=True)
    handoff_record = handoff_sub.add_parser("record")
    handoff_record.add_argument("--run-id")
    handoff_record.add_argument("--gate", required=True)
    handoff_record.add_argument("--exit-code", type=int, default=0)
    handoff_record.add_argument("--approved", action="store_true")
    handoff_record.add_argument("--reason")
    handoff_record.set_defaults(func=cmd_handoff_record)

    workspace = sub.add_parser("workspace")
    workspace_sub = workspace.add_subparsers(dest="command", required=True)
    workspace_init = workspace_sub.add_parser("init")
    workspace_init.add_argument("--run-id")
    workspace_init.add_argument("--source", default=".")
    workspace_init.set_defaults(func=cmd_workspace_init)

    resource = sub.add_parser("resource")
    resource_sub = resource.add_subparsers(dest="command", required=True)
    resource_run = resource_sub.add_parser("run")
    resource_run.add_argument("--run-id")
    resource_run.add_argument("--node-id", required=True)
    resource_run.add_argument("--trial-id", required=True)
    resource_run.add_argument("--purpose", default="benchmark")
    resource_run.add_argument("--cwd")
    resource_run.add_argument("--env-json")
    resource_run.add_argument("--metrics-path")
    resource_run.add_argument("--metrics-json")
    resource_run.add_argument("--seed")
    resource_run.add_argument("--benchmark-contract-version", default="v1")
    resource_run.add_argument("--notes", default="")
    resource_run.add_argument("--gpu", action="store_true")
    resource_run.add_argument("command", nargs=argparse.REMAINDER)
    resource_run.set_defaults(func=cmd_resource_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - helper CLI reports structured failures.
        return response("error", error=str(exc), error_type=exc.__class__.__name__)


if __name__ == "__main__":
    raise SystemExit(main())

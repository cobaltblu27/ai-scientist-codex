"""Canonical active research-loop workflow commands."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from cli.response import emit
from core.agents import research_agent_name
from core.state import (
    append_journal_event,
    atomic_write_json,
    audit_block_reason,
    block_for_manual_recovery,
    clear_active_run,
    config_path,
    data_hash,
    evaluate_loop_state_completion,
    journal_path,
    load_active_run,
    load_json_if_exists,
    load_loop_state,
    mutate_loop_state,
    node_evidence_fingerprint,
    run_dir,
    run_lock,
    selection_path,
    set_active_run,
    start_phase,
    utc_now,
    validate_active_run_contract,
    write_loop_state,
)

ACTIVE_MODES = {"scientist", "engineer", "custom"}
WORK_TERMINAL_STATUSES = {"completed", "cancelled", "failed", "abandoned", "accepted", "rejected"}
TASK_TERMINAL_STATUSES = WORK_TERMINAL_STATUSES
LEASE_ACTIVE_STATUSES = {"acquired", "running"}
RESOURCE_KEYS = ("gpus", "cpu_cores", "memory_mb")
REVISION_BRAINSTORM_SKILL = "skills/revision-brainstorm/SKILL.md"
CRITIC_METADATA_KEYS = {"critic_ref", "critic_verdict", "critic_completed_at", "critic_result_path", "critic_id", "critic_role"}


class ResearchError(ValueError):
    pass


def target_repo(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "target_repo", None) or Path.cwd()).resolve()


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "json_file", None):
        value = json.loads(Path(args.json_file).read_text())
    elif getattr(args, "json", None):
        value = json.loads(args.json)
    else:
        value = {}
    if not isinstance(value, dict):
        raise ResearchError("payload must be a JSON object")
    return value


def active_run(target: Path, run_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
    if run_id:
        state = load_loop_state(target, run_id)
        if state:
            reason = audit_block_reason(target, run_id, state)
            if reason:
                if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                    block_for_manual_recovery(target, run_id, state, reason)
                raise ResearchError(reason)
        return run_id, state
    active = load_active_run(target)
    if not isinstance(active, dict) or not isinstance(active.get("run_id"), str):
        raise ResearchError("no active AI Scientist run; pass --run-id")
    reason = validate_active_run_contract(active)
    if reason:
        raise ResearchError(f"active-run.json invalid: {reason}")
    rid = active["run_id"]
    state = load_loop_state(target, rid)
    if state:
        block_reason = audit_block_reason(target, rid, state)
        if block_reason:
            if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                block_for_manual_recovery(target, rid, state, block_reason)
            raise ResearchError(block_reason)
    return rid, state


def prompt_path_for(mode: str, kind: str) -> str | None:
    if kind == "orchestrator":
        return "skills/research-loop/SKILL.md"
    if kind == "worker":
        return "prompts/research-loop/worker.md"
    if kind == "baseline-worker":
        return "prompts/research-loop/baseline-worker.md"
    if kind in {"critic", "revision-critic"}:
        return f"prompts/research-loop/{mode}/critic.md"
    if kind == "revision-worker":
        return f"prompts/research-loop/{mode}/revision-worker.md"
    return None


def validate_mode(mode: str) -> str:
    if mode not in ACTIVE_MODES:
        raise ResearchError(f"invalid strictness mode: {mode}")
    return mode


def custom_criteria_from(payload: dict[str, Any]) -> Any:
    if "custom_criteria" in payload:
        return payload["custom_criteria"]
    research = payload.get("research") if isinstance(payload.get("research"), dict) else {}
    return research.get("custom_criteria")


def load_resource_config(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any] | None:
    if getattr(args, "resource_config", None):
        value = json.loads(Path(args.resource_config).read_text())
        if not isinstance(value, dict):
            raise ResearchError("--resource-config must point to a JSON object")
        return value
    value = payload.get("resources")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ResearchError("resources must be a JSON object")
    return deepcopy(value)


def selected_idea_from(payload: dict[str, Any]) -> Any:
    return payload.get("selected_idea") or payload.get("idea")


def idea_batch_from(payload: dict[str, Any], selected_idea: Any) -> list[dict[str, Any]]:
    batch = payload.get("idea_batch") or payload.get("ideas")
    if batch is None:
        if isinstance(selected_idea, dict):
            return [deepcopy(selected_idea)]
        return []
    if not isinstance(batch, list) or not batch:
        raise ResearchError("idea_batch must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    for index, idea in enumerate(batch, start=1):
        if not isinstance(idea, dict):
            raise ResearchError(f"idea_batch item {index} must be a JSON object")
        idea_id = idea.get("id")
        if not isinstance(idea_id, str) or not idea_id.strip():
            raise ResearchError(f"idea_batch item {index} missing id")
        normalized.append(deepcopy(idea))
    return normalized


def research_contract_from(payload: dict[str, Any], selected_idea: Any) -> Any:
    if isinstance(selected_idea, dict) and "research_contract" in selected_idea:
        return deepcopy(selected_idea["research_contract"])
    if "research_contract" in payload:
        return deepcopy(payload["research_contract"])
    return None


def frozen_arguments(target: Path, args: argparse.Namespace, payload: dict[str, Any], selected_idea: Any, idea_batch: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    provided = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    selected_idea_id = getattr(args, "selected_idea_id", None) or (selected_idea.get("id") if isinstance(selected_idea, dict) else None)
    return {
        "target_repo": str(target),
        "target_idea": deepcopy(provided.get("target_idea", selected_idea or {"idea_batch": idea_batch})),
        "selected_idea_id": selected_idea_id,
        "idea_batch_ids": [idea["id"] for idea in idea_batch],
        "python_environment": provided.get("python_environment", payload.get("python_environment")),
        "mode": mode,
        "target_venue": deepcopy(provided.get("target_venue", payload.get("target_venue"))),
    }


def initial_config(target: Path, args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    mode = validate_mode(str(args.strictness_mode or "scientist"))
    criteria = custom_criteria_from(payload)
    if mode == "custom" and not criteria:
        raise ResearchError("custom mode requires custom_criteria in research start JSON payload")
    resources = load_resource_config(args, payload)
    selected_idea = selected_idea_from(payload)
    idea_batch = idea_batch_from(payload, selected_idea)
    research_contract = research_contract_from(payload, selected_idea)
    if research_contract is None and idea_batch:
        research_contract = payload.get("research_contract")
    if not idea_batch:
        raise ResearchError("research start requires idea_batch or selected_idea")
    if research_contract is None:
        raise ResearchError("research start requires research_contract for campaign runs or selected_idea.research_contract for legacy runs")
    selected_idea_id = args.selected_idea_id or (selected_idea.get("id") if isinstance(selected_idea, dict) else None)
    cfg = {
        "schema_version": 1,
        "run_id": args.run_id,
        "target_repo": str(target),
        "strictness_mode": mode,
        "selected_idea_id": selected_idea_id,
        "selected_idea": selected_idea,
        "idea_batch": idea_batch,
        "campaign_mode": len(idea_batch) > 1 or selected_idea is None,
        "learning_notes_ref": str(run_dir(target, args.run_id) / "learning-notes.jsonl"),
        "discovery_notes_ref": str(run_dir(target, args.run_id) / "discovery-notes.md"),
        "arguments": frozen_arguments(target, args, payload, selected_idea, idea_batch, mode),
        "research_contract": research_contract,
        "custom_criteria": criteria,
        "resources": resources,
        "research": {
            "mode": mode,
            "prompt_root": "prompts/research-loop",
            "orchestrator_prompt": prompt_path_for(mode, "orchestrator"),
            "worker_agent": research_agent_name(mode, "worker"),
            "worker_prompt_source": prompt_path_for(mode, "worker"),
            "baseline_worker_agent": research_agent_name(mode, "baseline-worker"),
            "baseline_worker_prompt_source": prompt_path_for(mode, "baseline-worker"),
            "critic_agent": research_agent_name(mode, "critic"),
            "critic_prompt_source": prompt_path_for(mode, "critic"),
            "revision_worker_agent": research_agent_name(mode, "revision-worker"),
            "revision_worker_prompt_source": prompt_path_for(mode, "revision-worker"),
            "revision_brainstorm_skill": REVISION_BRAINSTORM_SKILL,
        },
        "created_at": utc_now(),
    }
    extra_config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    cfg.update(extra_config)
    cfg["strictness_mode"] = mode
    cfg["resources"] = resources
    cfg["selected_idea"] = selected_idea
    cfg["idea_batch"] = idea_batch
    cfg["campaign_mode"] = len(idea_batch) > 1 or selected_idea is None
    cfg["learning_notes_ref"] = str(run_dir(target, args.run_id) / "learning-notes.jsonl")
    cfg["discovery_notes_ref"] = str(run_dir(target, args.run_id) / "discovery-notes.md")
    cfg["selected_idea_id"] = selected_idea_id
    cfg["arguments"] = frozen_arguments(target, args, payload, selected_idea, idea_batch, mode)
    research = cfg.setdefault("research", {})
    if isinstance(research, dict):
        research.setdefault("worker_agent", research_agent_name(mode, "worker"))
        research.setdefault("worker_prompt_source", prompt_path_for(mode, "worker"))
        research.setdefault("baseline_worker_agent", research_agent_name(mode, "baseline-worker"))
        research.setdefault("baseline_worker_prompt_source", prompt_path_for(mode, "baseline-worker"))
        research.setdefault("critic_agent", research_agent_name(mode, "critic"))
        research.setdefault("critic_prompt_source", prompt_path_for(mode, "critic"))
        research.setdefault("revision_worker_agent", research_agent_name(mode, "revision-worker"))
        research.setdefault("revision_worker_prompt_source", prompt_path_for(mode, "revision-worker"))
        research.setdefault("revision_brainstorm_skill", REVISION_BRAINSTORM_SKILL)
    if research_contract is not None:
        cfg["research_contract"] = research_contract
    if criteria is not None:
        cfg["custom_criteria"] = criteria
    return cfg


def phase_state_or_error(state: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ResearchError(f"missing loop-state.json for run {run_id}")
    if state.get("phase") != "research":
        raise ResearchError(f"active run is not research: {state.get('phase')}")
    phase_state = state.get("state")
    if not isinstance(phase_state, dict):
        raise ResearchError("loop-state.json state must be an object")
    return phase_state


def resource_caps_from_config(cfg: dict[str, Any]) -> dict[str, Any] | None:
    resources = cfg.get("resources")
    return resources if isinstance(resources, dict) else None


def resource_scheduler_config(target: Path, run_id: str) -> dict[str, Any]:
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        return {}
    resources = cfg.get("resources")
    if not isinstance(resources, dict):
        return {}
    scheduler = resources.get("scheduler")
    if isinstance(scheduler, str):
        return {"type": scheduler}
    if isinstance(scheduler, dict):
        return scheduler
    return {}


def scheduler_option(args: argparse.Namespace, cfg: dict[str, Any], attr: str, key: str | None = None) -> Any:
    value = getattr(args, attr, None)
    if value is not None:
        return value
    return cfg.get(key or attr)


def valid_env_name(name: str) -> bool:
    return bool(name) and (name[0].isalpha() or name[0] == "_") and all(ch.isalnum() or ch == "_" for ch in name)


def parse_slurm_job_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            return line.split(";", 1)[0]
    return None


def write_slurm_job_script(path: Path, cwd: Path, command: list[str], env_record: dict[str, str], exit_code_path: Path) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"cd {shlex.quote(str(cwd))}",
    ]
    for key in sorted(env_record):
        if not valid_env_name(key):
            raise ResearchError(f"invalid environment variable name for Slurm export: {key}")
        lines.append(f"export {key}={shlex.quote(env_record[key])}")
    lines.extend(
        [
            "set +e",
            shlex.join(command),
            "status=$?",
            f"printf '%s\\n' \"$status\" > {shlex.quote(str(exit_code_path))}",
            "exit \"$status\"",
        ]
    )
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o755)


def slurm_extra_args(args: argparse.Namespace, cfg: dict[str, Any]) -> list[str]:
    values: list[str] = []
    configured = cfg.get("sbatch_args")
    if configured is None:
        configured = cfg.get("extra_args")
    if configured is not None:
        if not isinstance(configured, list) or not all(isinstance(item, str) for item in configured):
            raise ResearchError("resources.scheduler.sbatch_args must be a list of strings")
        values.extend(configured)
    values.extend(getattr(args, "sbatch_arg", None) or [])
    return values


def build_sbatch_argv(
    args: argparse.Namespace,
    cfg: dict[str, Any],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    job_script: Path,
) -> tuple[list[str], dict[str, Any]]:
    partition = scheduler_option(args, cfg, "partition")
    time_limit = scheduler_option(args, cfg, "time_limit", "time")
    gres = scheduler_option(args, cfg, "gres")
    cpus_per_task = scheduler_option(args, cfg, "cpus_per_task")
    mem = scheduler_option(args, cfg, "mem")
    job_name = scheduler_option(args, cfg, "job_name")

    sbatch_argv = [
        "sbatch",
        "--parsable",
        "--wait",
        "--chdir",
        str(cwd),
        "--output",
        str(stdout_path),
        "--error",
        str(stderr_path),
    ]
    options: dict[str, Any] = {}
    if partition:
        sbatch_argv.extend(["-p", str(partition)])
        options["partition"] = str(partition)
    if time_limit:
        sbatch_argv.append(f"--time={time_limit}")
        options["time"] = str(time_limit)
    if gres:
        sbatch_argv.append(f"--gres={gres}")
        options["gres"] = str(gres)
    if cpus_per_task:
        sbatch_argv.append(f"--cpus-per-task={cpus_per_task}")
        options["cpus_per_task"] = str(cpus_per_task)
    if mem:
        sbatch_argv.append(f"--mem={mem}")
        options["mem"] = str(mem)
    if job_name:
        sbatch_argv.append(f"--job-name={job_name}")
        options["job_name"] = str(job_name)
    extra_args = slurm_extra_args(args, cfg)
    sbatch_argv.extend(extra_args)
    if extra_args:
        options["sbatch_args"] = extra_args
    sbatch_argv.append(str(job_script))
    return sbatch_argv, options


def parse_cap(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"all", "unlimited"}:
        return None
    if isinstance(value, bool):
        raise ResearchError(f"resource cap {name} must be a non-negative integer or unlimited")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"resource cap {name} must be a non-negative integer or unlimited") from exc
    if parsed < 0:
        raise ResearchError(f"resource cap {name} must be non-negative")
    return parsed


def normalize_request(gpus: Any = 0, cpu_cores: Any = 0, memory_mb: Any = 0) -> dict[str, int]:
    request = {}
    for name, value in (("gpus", gpus), ("cpu_cores", cpu_cores), ("memory_mb", memory_mb)):
        if value is None:
            value = 0
        if isinstance(value, bool):
            raise ResearchError(f"resource request {name} must be a non-negative integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ResearchError(f"resource request {name} must be a non-negative integer") from exc
        if parsed < 0:
            raise ResearchError(f"resource request {name} must be non-negative")
        request[name] = parsed
    return request


def normalized_caps(cfg: dict[str, Any], request: dict[str, int] | None = None) -> dict[str, int | None]:
    caps = resource_caps_from_config(cfg)
    if not isinstance(caps, dict):
        raise ResearchError("resource_caps_missing")
    if "max_parallel" not in caps:
        raise ResearchError("resource_caps_missing:max_parallel")
    max_parallel = parse_cap(caps.get("max_parallel"), "max_parallel")
    if max_parallel is None or max_parallel <= 0:
        raise ResearchError("resource cap max_parallel must be a positive integer")
    normalized: dict[str, int | None] = {"max_parallel": max_parallel}
    request = request or {}
    for key in RESOURCE_KEYS:
        if request.get(key, 0) > 0 and key not in caps:
            raise ResearchError(f"resource_caps_missing:{key}")
        normalized[key] = parse_cap(caps.get(key), key) if key in caps else 0
    return normalized


def active_leases(phase_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = phase_state.get("resources") if isinstance(phase_state.get("resources"), dict) else {}
    leases = resources.get("leases") if isinstance(resources.get("leases"), dict) else {}
    return {
        str(lease_id): lease
        for lease_id, lease in leases.items()
        if isinstance(lease, dict) and str(lease.get("status") or "acquired") in LEASE_ACTIVE_STATUSES
    }


def resource_usage(leases: dict[str, dict[str, Any]]) -> dict[str, int]:
    usage = {"parallel": len(leases), "gpus": 0, "cpu_cores": 0, "memory_mb": 0}
    for lease in leases.values():
        request = lease.get("request") if isinstance(lease.get("request"), dict) else {}
        for key in RESOURCE_KEYS:
            try:
                usage[key] += int(request.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return usage


def empty_resource_queue() -> dict[str, list[Any]]:
    return {"pending": [], "released": [], "completed": []}


def normalize_resource_queue(value: Any) -> dict[str, list[Any]]:
    queue = empty_resource_queue()
    if isinstance(value, dict):
        for bucket in queue:
            entries = value.get(bucket)
            if isinstance(entries, list):
                queue[bucket] = entries
    return queue


def merge_resource_queue(current: Any, patch: Any) -> dict[str, list[Any]]:
    queue = normalize_resource_queue(current)
    if isinstance(patch, dict):
        for bucket in queue:
            entries = patch.get(bucket)
            if isinstance(entries, list):
                queue[bucket] = entries
    return queue


def resource_queue_summary(phase_state: dict[str, Any]) -> dict[str, Any]:
    queue = normalize_resource_queue(phase_state.get("resource_queue"))
    return {
        "counts": {bucket: len(entries) for bucket, entries in queue.items()},
        "pending": queue["pending"],
        "released": queue["released"],
        "completed": queue["completed"],
    }


def can_fit(caps: dict[str, int | None], usage: dict[str, int], request: dict[str, int]) -> bool:
    max_parallel = caps["max_parallel"]
    if isinstance(max_parallel, int) and usage["parallel"] + 1 > max_parallel:
        return False
    for key in RESOURCE_KEYS:
        cap = caps.get(key)
        if cap is not None and usage[key] + request.get(key, 0) > cap:
            return False
    return True


def can_ever_fit(caps: dict[str, int | None], request: dict[str, int]) -> bool:
    for key in RESOURCE_KEYS:
        cap = caps.get(key)
        if cap is not None and request.get(key, 0) > cap:
            return False
    return True


def resource_summary(target: Path, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_if_exists(config_path(target, run_id))
    cfg = cfg if isinstance(cfg, dict) else {}
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    leases = active_leases(phase_state)
    summary: dict[str, Any] = {
        "active_leases": leases,
        "active_lease_count": len(leases),
        "resource_queue": resource_queue_summary(phase_state),
    }
    caps = resource_caps_from_config(cfg)
    if isinstance(caps, dict):
        try:
            normalized = normalized_caps(cfg, {})
            usage = resource_usage(leases)
            available = {"parallel": int(normalized["max_parallel"]) - usage["parallel"]}
            for key in RESOURCE_KEYS:
                cap = normalized.get(key)
                available[key] = None if cap is None else cap - usage[key]
            summary.update({"caps": caps, "usage": usage, "available": available})
        except ResearchError as exc:
            summary.update({"caps": caps, "warning": str(exc)})
    else:
        summary["warning"] = "resource_caps_missing"
    return summary


def terminal_task_ids(phase_state: dict[str, Any]) -> set[str]:
    tasks = phase_state.get("tasks") if isinstance(phase_state.get("tasks"), dict) else {}
    return {
        str(task_id)
        for task_id, task in tasks.items()
        if isinstance(task, dict) and str(task.get("status") or "") in TASK_TERMINAL_STATUSES
    }


def open_task_ids(phase_state: dict[str, Any]) -> list[str]:
    tasks = phase_state.get("tasks") if isinstance(phase_state.get("tasks"), dict) else {}
    terminal = terminal_task_ids(phase_state)
    return sorted(str(task_id) for task_id in tasks if str(task_id) not in terminal)


def open_work_ids(phase_state: dict[str, Any]) -> list[str]:
    work = phase_state.get("work") if isinstance(phase_state.get("work"), dict) else {}
    return sorted(
        str(work_id)
        for work_id, record in work.items()
        if not isinstance(record, dict) or str(record.get("status") or "") not in WORK_TERMINAL_STATUSES
    )


def update_nodes_from_result(phase_state: dict[str, Any], payload: dict[str, Any]) -> None:
    nodes = phase_state.setdefault("nodes", {})
    node_payload = payload.get("node") if isinstance(payload.get("node"), dict) else None
    if node_payload:
        node_id = str(node_payload.get("node_id") or node_payload.get("id") or "").strip()
        if node_id:
            current = nodes.setdefault(node_id, {})
            current.update(node_payload)
            current.setdefault("node_id", node_id)
            current["updated_at"] = utc_now()
    bulk = payload.get("nodes")
    if isinstance(bulk, dict):
        for node_id, node in bulk.items():
            if isinstance(node, dict):
                current = nodes.setdefault(str(node_id), {})
                current.update(node)
                current.setdefault("node_id", str(node_id))
                current["updated_at"] = utc_now()
    elif isinstance(bulk, list):
        for node in bulk:
            if isinstance(node, dict):
                node_id = str(node.get("node_id") or node.get("id") or "").strip()
                if node_id:
                    current = nodes.setdefault(node_id, {})
                    current.update(node)
                    current.setdefault("node_id", node_id)
                    current["updated_at"] = utc_now()


def stamp_critic_fingerprints(phase_state: dict[str, Any], nodes_patch: dict[str, Any]) -> None:
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    for node_id, patch in nodes_patch.items():
        if not isinstance(patch, dict) or not any(key in patch for key in CRITIC_METADATA_KEYS):
            continue
        current = nodes.get(str(node_id))
        if not isinstance(current, dict):
            continue
        fingerprint = node_evidence_fingerprint(current)
        current["node_evidence_fingerprint"] = fingerprint
        if "critic_evidence_fingerprint" not in patch:
            current["critic_evidence_fingerprint"] = fingerprint


def cmd_research_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    payload = load_payload(args)
    cfg = initial_config(target, args, payload)
    mode = cfg["strictness_mode"]
    initial_state = {
        "mode": mode,
        "custom_criteria": cfg.get("custom_criteria"),
        "selected_idea_id": cfg.get("selected_idea_id"),
        "idea_batch": deepcopy(cfg.get("idea_batch") or []),
        "campaign_mode": bool(cfg.get("campaign_mode")),
        "learning_notes": {
            "path": cfg.get("learning_notes_ref"),
            "status": "active",
        },
        "discovery_notes": {
            "path": cfg.get("discovery_notes_ref"),
            "status": "active",
        },
        "orchestrator": {
            "role": "main_codex_session",
            "next_action": "plan",
            "next_action_details": {"reason": "research run started"},
            "prompt_path": prompt_path_for(mode, "orchestrator"),
            "last_checkpoint_at": utc_now(),
        },
        "tasks": {},
        "work": {},
        "baseline": {
            "required": False,
            "status": "not_required",
            "fixed_split_dir": str(run_dir(target, args.run_id) / "baseline" / "splits"),
            "split_manifest_ref": str(run_dir(target, args.run_id) / "baseline" / "baseline.json"),
            "baseline_score_refs": [],
            "repo_refs": [],
        },
        "nodes": {},
        "resource_queue": empty_resource_queue(),
        "resources": {"caps": cfg.get("resources"), "leases": {}, "completed_leases": {}, "events": []},
        "selection": {"status": "pending", "selected_node": None},
    }
    state_override = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    initial_state.update(state_override)
    state = start_phase(target, args.run_id, "research", initial_state)
    (run_dir(target, args.run_id) / "baseline").mkdir(parents=True, exist_ok=True)
    set_active_run(
        target,
        args.run_id,
        "research",
        "active",
        codex_session_id=args.codex_session_id or os.environ.get("CODEX_SESSION_ID"),
        codex_thread_id=args.codex_thread_id or os.environ.get("CODEX_THREAD_ID"),
    )
    atomic_write_json(config_path(target, args.run_id), cfg)
    learning_notes_ref = cfg.get("learning_notes_ref")
    if isinstance(learning_notes_ref, str) and learning_notes_ref:
        notes_path = Path(learning_notes_ref)
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.touch(exist_ok=True)
    discovery_notes_ref = cfg.get("discovery_notes_ref")
    if isinstance(discovery_notes_ref, str) and discovery_notes_ref:
        notes_path = Path(discovery_notes_ref)
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        if not notes_path.exists():
            notes_path.write_text(
                "# Discovery Notes\n\n"
                "## Current Best Understanding\n\n"
                "No discovery synthesis recorded yet.\n\n"
                "## What Worked\n\n"
                "- TBD\n\n"
                "## What Did Not Work\n\n"
                "- TBD\n\n"
                "## Data And Evaluation Findings\n\n"
                "- TBD\n\n"
                "## Model And Mechanism Hypotheses\n\n"
                "- TBD\n\n"
                "## Transferable Insights\n\n"
                "- TBD\n\n"
                "## Branch Seeds\n\n"
                "- TBD\n\n"
                "## Things To Avoid Repeating\n\n"
                "- TBD\n\n"
                "## Node Notes\n\n",
                encoding="utf-8",
            )
    append_journal_event(target, args.run_id, "state_transition", details={"command": "research start", "state_hash": data_hash(state)})
    return emit("ok", run_id=args.run_id, state_path=str(run_dir(target, args.run_id) / "loop-state.json"), config_path=str(config_path(target, args.run_id)), mode=mode)


def cmd_research_resume(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    phase_state = phase_state_or_error(state, run_id)
    orchestrator = phase_state.get("orchestrator") if isinstance(phase_state.get("orchestrator"), dict) else {}
    append_journal_event(target, run_id, "state_transition", details={"command": "research resume", "next_action": orchestrator.get("next_action")})
    set_active_run(target, run_id, "research", "active")
    return emit(
        "ok",
        run_id=run_id,
        mode=phase_state.get("mode"),
        next_action=orchestrator.get("next_action"),
        next_action_details=orchestrator.get("next_action_details", {}),
        open_work=open_work_ids(phase_state),
        open_tasks=open_task_ids(phase_state),
        baseline=phase_state.get("baseline") if isinstance(phase_state.get("baseline"), dict) else None,
        selected_node=(phase_state.get("selection") or {}).get("selected_node") if isinstance(phase_state.get("selection"), dict) else None,
        resources=resource_summary(target, run_id, state),
    )


def cmd_research_checkpoint(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        patch = payload.get("state") if isinstance(payload.get("state"), dict) else payload
        for key in ("baseline", "work", "tasks", "resources", "selection"):
            if isinstance(patch.get(key), dict):
                current = phase_state.setdefault(key, {})
                current.update(patch[key])
        if isinstance(patch.get("resource_queue"), dict):
            phase_state["resource_queue"] = merge_resource_queue(phase_state.get("resource_queue"), patch["resource_queue"])
        if isinstance(patch.get("nodes"), dict):
            nodes = phase_state.setdefault("nodes", {})
            for node_id, node_patch in patch["nodes"].items():
                if isinstance(node_patch, dict):
                    current_node = nodes.setdefault(str(node_id), {})
                    current_node.update(node_patch)
                    current_node.setdefault("node_id", str(node_id))
                    current_node["updated_at"] = utc_now()
                else:
                    nodes[str(node_id)] = node_patch
            stamp_critic_fingerprints(phase_state, patch["nodes"])
        if isinstance(patch.get("orchestrator"), dict):
            phase_state.setdefault("orchestrator", {}).update(patch["orchestrator"])
        orchestrator = phase_state.setdefault("orchestrator", {})
        if "next_action" in payload:
            orchestrator["next_action"] = payload["next_action"]
        if "next_action_details" in payload:
            orchestrator["next_action_details"] = payload["next_action_details"]
        if "reason" in payload:
            details = orchestrator.setdefault("next_action_details", {})
            if isinstance(details, dict):
                details["reason"] = payload["reason"]
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "research checkpoint", "payload": payload}, mutator)
    return emit("ok", run_id=run_id)


def cmd_research_select(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)
    node_id = args.node_id
    evidence_refs = list(args.evidence_ref or [])
    payload_refs = payload.get("evidence_refs")
    if isinstance(payload_refs, list):
        evidence_refs.extend(str(item) for item in payload_refs)
    summary = args.summary or payload.get("summary")
    rationale = args.acceptance_rationale or payload.get("acceptance_rationale")
    node_payload = payload.get("node") if isinstance(payload.get("node"), dict) else {}

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        nodes = phase_state.setdefault("nodes", {})
        node = nodes.setdefault(node_id, {})
        node.update(node_payload)
        node.setdefault("node_id", node_id)
        node["status"] = str(node.get("status") or "accepted")
        if node["status"] != "accepted":
            raise ResearchError("research select requires an accepted node")
        if summary:
            node["summary"] = summary
        if evidence_refs:
            node["evidence_refs"] = evidence_refs
        if rationale:
            node["acceptance_rationale"] = rationale
        node["updated_at"] = utc_now()
        phase_state["selected_node"] = node_id
        phase_state["selection"] = {
            "status": "final",
            "selected_node": node_id,
            "summary": summary or node.get("summary"),
            "evidence_refs": evidence_refs or node.get("evidence_refs", []),
            "acceptance_rationale": rationale or node.get("acceptance_rationale"),
            "selected_at": utc_now(),
        }

    updated = mutate_loop_state(target, run_id, "selection", {"command": "research select", "node_id": node_id}, mutator)
    selection = updated["state"]["selection"]
    atomic_write_json(selection_path(target, run_id), selection)
    return emit("ok", run_id=run_id, selection=selection)


def cmd_research_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not isinstance(state, dict):
        raise ResearchError(f"missing loop-state.json for run {run_id}")
    audit = load_payload(args)
    if audit.get("passed") is not True:
        raise ResearchError("completion audit must include passed=true")
    simulated = deepcopy(state)
    simulated["active"] = False
    simulated["phase_status"] = "complete"
    simulated["completion_audit"] = audit
    result = evaluate_loop_state_completion(simulated)
    if not result.complete:
        raise ResearchError(f"research completion blocked: {result.reason}")

    def mutator(new_state: dict[str, Any]) -> None:
        new_state["active"] = False
        new_state["phase_status"] = "complete"
        new_state["completed_at"] = utc_now()
        new_state["completion_audit"] = audit

    mutate_loop_state(target, run_id, "state_transition", {"command": "research complete"}, mutator)
    set_active_run(target, run_id, "research", "validating")
    return emit("ok", run_id=run_id, active_status="validating")


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
    return emit("ok", run_id=run_id, phase_status="cancelled")


def acquire_lease(target: Path, run_id: str, task_id: str, request: dict[str, int], timeout_sec: float, poll_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_sec)
    last_reason = "resource_unavailable"
    while True:
        with run_lock(target, run_id):
            state = load_loop_state(target, run_id)
            phase_state = phase_state_or_error(state, run_id)
            cfg = load_json_if_exists(config_path(target, run_id))
            if not isinstance(cfg, dict):
                raise ResearchError(f"missing config.json for run {run_id}")
            caps = normalized_caps(cfg, request)
            if not can_ever_fit(caps, request):
                raise ResearchError("resource_request_exceeds_caps")
            leases = active_leases(phase_state)
            usage = resource_usage(leases)
            if can_fit(caps, usage, request):
                lease_id = f"lease-{uuid.uuid4().hex[:16]}"
                lease = {
                    "lease_id": lease_id,
                    "task_id": task_id,
                    "status": "acquired",
                    "request": request,
                    "created_at": utc_now(),
                }
                resources = phase_state.setdefault("resources", {})
                resources.setdefault("caps", cfg.get("resources"))
                resources.setdefault("leases", {})[lease_id] = lease
                tasks = phase_state.setdefault("tasks", {})
                if isinstance(tasks.get(task_id), dict):
                    tasks[task_id]["resource_lease_id"] = lease_id
                    tasks[task_id]["status"] = "running"
                    tasks[task_id]["updated_at"] = utc_now()
                work = phase_state.setdefault("work", {})
                if isinstance(work.get(task_id), dict):
                    work[task_id]["resource_lease_id"] = lease_id
                    work[task_id]["status"] = "running"
                    work[task_id]["updated_at"] = utc_now()
                write_loop_state(target, run_id, state)
                append_journal_event(target, run_id, "resource_event", resource_id=lease_id, details={"command": "resource acquire", "task_id": task_id, "request": request})
                return lease
            last_reason = "resource_unavailable"
        if time.monotonic() >= deadline:
            raise ResearchError(last_reason)
        time.sleep(max(0.1, poll_sec))


def release_lease(target: Path, run_id: str, lease_id: str, *, status: str = "released", details: dict[str, Any] | None = None) -> dict[str, Any]:
    with run_lock(target, run_id):
        state = load_loop_state(target, run_id)
        phase_state = phase_state_or_error(state, run_id)
        resources = phase_state.setdefault("resources", {})
        leases = resources.setdefault("leases", {})
        lease = leases.get(lease_id)
        if not isinstance(lease, dict):
            raise ResearchError(f"unknown resource lease: {lease_id}")
        lease = dict(lease)
        lease["status"] = status
        lease["released_at"] = utc_now()
        if details:
            lease["details"] = details
        leases.pop(lease_id, None)
        resources.setdefault("completed_leases", {})[lease_id] = lease
        write_loop_state(target, run_id, state)
    append_journal_event(target, run_id, "resource_event", resource_id=lease_id, details={"command": "resource release", "status": status, **(details or {})})
    return lease


def cmd_resource_status(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not isinstance(state, dict):
        raise ResearchError(f"missing loop-state.json for run {run_id}")
    return emit("ok", run_id=run_id, resources=resource_summary(target, run_id, state))


def cmd_resource_acquire(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    request = normalize_request(args.gpus, args.cpu_cores, args.memory_mb)
    lease = acquire_lease(target, run_id, args.task_id, request, args.timeout_sec, args.poll_sec)
    return emit("ok", run_id=run_id, lease=lease)


def cmd_resource_release(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    lease = release_lease(target, run_id, args.lease_id)
    return emit("ok", run_id=run_id, lease=lease)


def cmd_resource_run(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ResearchError("resource run requires a command after --")
    request = normalize_request(args.gpus, args.cpu_cores, args.memory_mb)
    lease = acquire_lease(target, run_id, args.task_id, request, args.timeout_sec, args.poll_sec)
    lease_id = lease["lease_id"]
    command_ref = run_dir(target, run_id) / "logs" / "resources" / args.task_id / lease_id / "command.json"
    command_spec: dict[str, Any] = {}
    return_code: int | None = None
    try:
        record_dir = command_ref.parent
        record_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = record_dir / "stdout.log"
        stderr_path = record_dir / "stderr.log"
        cwd = Path(args.cwd).resolve() if args.cwd else target
        env = os.environ.copy()
        env_updates = json.loads(args.env_json) if args.env_json else {}
        if not isinstance(env_updates, dict):
            raise ResearchError("--env-json must be a JSON object")
        env_record = {str(key): str(value) for key, value in env_updates.items()}
        env.update(env_record)
        scheduler_cfg = resource_scheduler_config(target, run_id)
        scheduler = args.scheduler or str(scheduler_cfg.get("type") or scheduler_cfg.get("scheduler") or "local")
        if scheduler not in {"local", "slurm"}:
            raise ResearchError(f"unsupported resource scheduler: {scheduler}")
        command_spec = {
            "argv": command,
            "cwd": str(cwd),
            "env": {key: env_record[key] for key in sorted(env_record)},
            "resource_lease_id": lease_id,
            "request": request,
            "scheduler": scheduler,
            "started_at": utc_now(),
            "purpose": args.purpose,
            "notes": args.notes,
        }
        if scheduler == "slurm":
            job_script = record_dir / "job.sh"
            exit_code_path = record_dir / "exit_code.txt"
            write_slurm_job_script(job_script, cwd, command, env_record, exit_code_path)
            sbatch_argv, slurm_options = build_sbatch_argv(args, scheduler_cfg, cwd, stdout_path, stderr_path, job_script)
            command_spec.update(
                {
                    "job_script": str(job_script),
                    "sbatch_argv": sbatch_argv,
                    "slurm": slurm_options,
                }
            )
        command_spec["command_spec_hash"] = data_hash(command_spec)
        atomic_write_json(command_ref, command_spec)

        if scheduler == "slurm":
            sbatch_proc = subprocess.run(command_spec["sbatch_argv"], cwd=target, env=env, text=True, capture_output=True, check=False)
            slurm_job_id = parse_slurm_job_id(sbatch_proc.stdout)
            if not stdout_path.exists():
                stdout_path.write_text(sbatch_proc.stdout if sbatch_proc.returncode != 0 else "")
            if not stderr_path.exists():
                stderr_path.write_text(sbatch_proc.stderr)
            exit_code_path = record_dir / "exit_code.txt"
            if exit_code_path.exists():
                try:
                    return_code = int(exit_code_path.read_text().strip())
                except ValueError:
                    return_code = sbatch_proc.returncode
            else:
                return_code = sbatch_proc.returncode
            command_spec.update(
                {
                    "scheduler_exit_code": sbatch_proc.returncode,
                    "sbatch_stdout": sbatch_proc.stdout,
                    "sbatch_stderr": sbatch_proc.stderr,
                    "slurm_job_id": slurm_job_id,
                }
            )
        else:
            proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
            stdout_path.write_text(proc.stdout)
            stderr_path.write_text(proc.stderr)
            return_code = proc.returncode

        metrics: dict[str, Any] | None = None
        metrics_source = None
        if args.metrics_json:
            metrics = json.loads(args.metrics_json)
            if not isinstance(metrics, dict):
                raise ResearchError("--metrics-json must be a JSON object")
            metrics_source = "inline_metrics_json"
        elif args.metrics_path:
            metrics_path = Path(args.metrics_path)
            if not metrics_path.is_absolute():
                metrics_path = cwd / metrics_path
            if metrics_path.exists():
                value = json.loads(metrics_path.read_text())
                if not isinstance(value, dict):
                    raise ResearchError("--metrics-path must contain a JSON object")
                metrics = value
                metrics_source = str(metrics_path)
        command_spec.update(
            {
                "completed_at": utc_now(),
                "exit_code": return_code,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "metrics": metrics,
                "metrics_source": metrics_source,
            }
        )
        atomic_write_json(command_ref, command_spec)
        status = "completed" if return_code == 0 else "failed"
        release_lease(target, run_id, lease_id, status=status, details={"exit_code": return_code, "command_ref": str(command_ref), "scheduler": command_spec.get("scheduler"), "slurm_job_id": command_spec.get("slurm_job_id")})
    except Exception as exc:
        release_lease(target, run_id, lease_id, status="failed", details={"error": str(exc), "command_ref": str(command_ref)})
        raise
    assert return_code is not None
    append_journal_event(
        target,
        run_id,
        "resource_event",
        resource_id=lease_id,
        details={
            "command": "resource run",
            "task_id": args.task_id,
            "exit_code": return_code,
            "command_ref": str(command_ref),
            "command_spec_hash": command_spec["command_spec_hash"],
            "scheduler": command_spec.get("scheduler"),
            "slurm_job_id": command_spec.get("slurm_job_id"),
        },
    )
    return emit("ok" if return_code == 0 else "error", run_id=run_id, task_id=args.task_id, lease_id=lease_id, exit_code=return_code, command_ref=str(command_ref))

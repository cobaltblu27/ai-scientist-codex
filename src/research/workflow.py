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
from core.frontmatter import read_frontmatter
from core.state import (
    append_journal_event,
    atomic_write_json,
    audit_block_reason,
    clear_active_run,
    config_md_path,
    data_hash,
    evaluate_loop_state_completion,
    is_terminal_status,
    load_active_run,
    load_loop_state,
    mutate_loop_state,
    run_dir,
    run_lock,
    selection_path,
    set_active_run,
    utc_now,
    validate_active_run_contract,
    write_loop_state,
)

LEASE_ACTIVE_STATUSES = {"acquired", "running"}
RESOURCE_KEYS = ("gpus", "cpu_cores", "memory_mb")
# config.md frontmatter is flat; resource caps use these keys (docs/SCHEMA.md section 3.5 leaves them free).
RESOURCE_CAP_FRONTMATTER_KEYS = {
    "max_parallel": "resource_max_parallel",
    "gpus": "resource_gpus",
    "cpu_cores": "resource_cpu_cores",
    "memory_mb": "resource_memory_mb",
}
SCHEDULER_FRONTMATTER_KEYS = {
    "type": "resource_scheduler",
    "partition": "slurm_partition",
    "time": "slurm_time",
    "gres": "slurm_gres",
    "cpus_per_task": "slurm_cpus_per_task",
    "mem": "slurm_mem",
    "job_name": "slurm_job_name",
}


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
            raise ResearchError(block_reason)
    return rid, state


def phase_state_or_error(state: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ResearchError(f"missing loop-state.json for run {run_id}")
    if state.get("phase") != "research":
        raise ResearchError(f"active run is not research: {state.get('phase')}")
    phase_state = state.get("state")
    if not isinstance(phase_state, dict):
        raise ResearchError("loop-state.json state must be an object")
    return phase_state


def safe_log_name(value: str | None, default: str = "item") -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value or "").strip()).strip("-")
    return clean or default


def resource_config(target: Path, run_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Frozen resource policy: `state.resources.caps` in loop-state.json, else `resource_*` keys in config.md frontmatter."""
    state = state if isinstance(state, dict) else load_loop_state(target, run_id)
    phase_state = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else {}
    resources = phase_state.get("resources") if isinstance(phase_state.get("resources"), dict) else {}
    caps = resources.get("caps")
    if isinstance(caps, dict):
        return deepcopy(caps)
    frontmatter = read_frontmatter(config_md_path(target, run_id))
    caps = {key: frontmatter[fm_key] for key, fm_key in RESOURCE_CAP_FRONTMATTER_KEYS.items() if fm_key in frontmatter}
    scheduler = {key: frontmatter[fm_key] for key, fm_key in SCHEDULER_FRONTMATTER_KEYS.items() if fm_key in frontmatter}
    if scheduler:
        caps["scheduler"] = scheduler
    return caps


def resource_caps_from_config(cfg: dict[str, Any]) -> dict[str, Any] | None:
    return cfg if isinstance(cfg, dict) and cfg else None


def resource_scheduler_config(target: Path, run_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    scheduler = resource_config(target, run_id, state).get("scheduler")
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
    cfg = resource_config(target, run_id, state)
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
        if isinstance(task, dict) and is_terminal_status(task.get("status"))
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
        if not isinstance(record, dict) or not is_terminal_status(record.get("status"))
    )


def cmd_research_resume(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    phase_state = phase_state_or_error(state, run_id)
    orchestrator = phase_state.get("orchestrator") if isinstance(phase_state.get("orchestrator"), dict) else {}
    append_journal_event(
        target,
        run_id,
        "state_transition",
        details={
            "command": "research resume",
            "next_action": orchestrator.get("next_action"),
        },
    )
    set_active_run(target, run_id, "research", "active")
    return emit(
        "ok",
        run_id=run_id,
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
    node_id = args.node_id
    evidence_refs = list(args.evidence_ref or [])
    summary = args.summary
    rationale = args.acceptance_rationale

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        nodes = phase_state.setdefault("nodes", {})
        node = nodes.setdefault(node_id, {})
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
    selection = {"run_id": run_id, **updated["state"]["selection"]}
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
    simulated["phase_status"] = "success"
    result = evaluate_loop_state_completion(simulated)
    if not result.complete:
        raise ResearchError(f"research completion blocked: {result.reason}")

    def mutator(new_state: dict[str, Any]) -> None:
        new_state["active"] = False
        new_state["phase_status"] = "success"
        new_state["run_outcome"] = "success"
        new_state["completed_at"] = utc_now()
        new_state["completion_audit"] = audit

    mutate_loop_state(target, run_id, "state_transition", {"command": "research complete"}, mutator)
    set_active_run(target, run_id, "research", "success")
    return emit("ok", run_id=run_id, phase_status="success", active_status="success")


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
            cfg = resource_config(target, run_id, state)
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
                resources.setdefault("caps", cfg)
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

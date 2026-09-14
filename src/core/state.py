#!/usr/bin/env python3
"""State helpers for durable AI Scientist run artifacts."""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Vocabulary from docs/SCHEMA.md section 3.3.
TERMINAL_PHASE_STATUSES = {"success", "exhausted", "cancelled", "blocked", "complete"}
ALLOW_WITH_REASON_STATUSES = {"cancelled", "blocked"}
JOURNAL_EVENT_TYPES = {
    "state_transition",
    "api_call",
    "resource_event",
    "subagent_event",
    "critic_event",
    "handoff",
    "validation",
    "selection",
    "setup",
    "dependency",
    "workspace",
    "note",
    "finding",
    "message",
}
# Shared terminal set for nodes, work items, and tasks. Any other lowercase word is live.
WORK_TERMINAL_STATUSES = {"completed", "cancelled", "failed", "abandoned", "accepted", "rejected"}
BASELINE_READY_STATUSES = {"ready", "completed"}


def is_terminal_status(status: Any) -> bool:
    return str(status or "") in WORK_TERMINAL_STATUSES


def open_resource_queue_ids(phase_state: dict[str, Any]) -> list[str]:
    queue = phase_state.get("resource_queue") if isinstance(phase_state.get("resource_queue"), dict) else {}
    open_ids: list[str] = []
    for bucket in ("pending", "released"):
        entries = queue.get(bucket)
        if not isinstance(entries, list):
            if entries:
                open_ids.append(bucket)
            continue
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                identifier = entry.get("job_id") or entry.get("work_id") or entry.get("node_id") or f"{bucket}[{index}]"
            else:
                identifier = entry or f"{bucket}[{index}]"
            open_ids.append(f"{bucket}:{identifier}")
    return sorted(str(item) for item in open_ids)


@dataclass(frozen=True)
class CompletionResult:
    complete: bool
    reason: str
    state: dict[str, Any] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ai_root(target_repo: Path) -> Path:
    target_repo = target_repo.resolve()
    return target_repo if target_repo.name == ".ai-scientist" else target_repo / ".ai-scientist"


def active_run_path(target_repo: Path) -> Path:
    return ai_root(target_repo) / "active-run.json"


def run_dir(target_repo: Path, run_id: str) -> Path:
    return ai_root(target_repo) / "runs" / run_id


def loop_state_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "loop-state.json"


def journal_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "journal.jsonl"


def config_path(target_repo: Path, run_id: str) -> Path:
    """Legacy JSON config location; research runs freeze configuration in config.md instead."""
    return run_dir(target_repo, run_id) / "config.json"


def config_md_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "config.md"


def selection_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "selection.json"


def node_dir(target_repo: Path, run_id: str, node_id: str) -> Path:
    return run_dir(target_repo, run_id) / "nodes" / node_id


def node_json_path(target_repo: Path, run_id: str, node_id: str) -> Path:
    return node_dir(target_repo, run_id, node_id) / "node.json"


def run_lock_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "locks" / "run.lock"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_json_if_exists(path: Path) -> Any | None:
    if not path.exists():
        return None
    return load_json(path)


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def data_hash(data: Any) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def load_jsonl_if_exists(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records


@contextmanager
def run_lock(target_repo: Path, run_id: str, timeout_sec: float = 10.0):
    path = run_lock_path(target_repo, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_sec
    payload = {"pid": os.getpid(), "created_at": utc_now()}
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
            break
        except FileExistsError:
            if stale_pid_lock(path):
                try:
                    path.unlink()
                    continue
                except FileNotFoundError:
                    continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for AI Scientist run lock: {path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stale_pid_lock(path: Path) -> bool:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    pid = value.get("pid") if isinstance(value, dict) else None
    return isinstance(pid, int) and not pid_is_running(pid)


def append_journal_event(
    target_repo: Path,
    run_id: str,
    event_type: str,
    *,
    details: dict[str, Any] | None = None,
    transition_id: str | None = None,
    node_id: str | None = None,
    subagent_id: str | None = None,
    resource_id: str | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
) -> dict[str, Any]:
    if event_type not in JOURNAL_EVENT_TYPES:
        raise ValueError(f"unknown journal event_type: {event_type}")
    record = {
        "event_type": event_type,
        "timestamp": utc_now(),
        "run_id": run_id,
        "details": details or {},
    }
    optional = {
        "transition_id": transition_id,
        "node_id": node_id,
        "subagent_id": subagent_id,
        "resource_id": resource_id,
        "before_hash": before_hash,
        "after_hash": after_hash,
    }
    record.update({key: value for key, value in optional.items() if value is not None})
    append_jsonl(journal_path(target_repo, run_id), record)
    return record


def validate_journal_record_contract(record: dict[str, Any]) -> str | None:
    if record.get("event_type") not in JOURNAL_EVENT_TYPES:
        return "event_type_invalid"
    for key in ("timestamp", "run_id"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            return f"{key}_invalid"
    if not isinstance(record.get("details"), dict):
        return "details_invalid"
    for key in ("transition_id", "node_id", "subagent_id", "resource_id", "before_hash", "after_hash"):
        if key in record and not isinstance(record.get(key), str):
            return f"{key}_invalid"
    return None


def journal_has_event(
    target_repo: Path,
    run_id: str,
    event_type: str,
    *,
    gate: str | None = None,
    approved: bool | None = None,
    exit_code: int | None = None,
) -> bool:
    for record in load_jsonl_if_exists(journal_path(target_repo, run_id)):
        reason = validate_journal_record_contract(record)
        if reason:
            raise ValueError(f"invalid journal record: {reason}")
        if record.get("event_type") != event_type:
            continue
        details = record.get("details") if isinstance(record.get("details"), dict) else {}
        if gate is not None and details.get("gate") != gate:
            continue
        if approved is not None and details.get("approved") is not approved:
            continue
        if exit_code is not None:
            value = details.get("exit_code", details.get("validator_exit_code"))
            if value != exit_code:
                continue
        return True
    return False


def journal_has_transition(target_repo: Path, run_id: str, transition_id: str) -> bool:
    for record in load_jsonl_if_exists(journal_path(target_repo, run_id)):
        reason = validate_journal_record_contract(record)
        if reason:
            raise ValueError(f"invalid journal record: {reason}")
        if record.get("transition_id") == transition_id:
            return True
        details = record.get("details") if isinstance(record.get("details"), dict) else {}
        if details.get("transition_id") == transition_id:
            return True
    return False


def audit_block_reason(target_repo: Path, run_id: str, state: dict[str, Any]) -> str | None:
    """Return a reason when loop-state.json and journal.jsonl disagree, else None."""
    last_transition_id = state.get("last_transition_id")
    if isinstance(last_transition_id, str) and last_transition_id and not journal_has_transition(target_repo, run_id, last_transition_id):
        return f"state_journal_mismatch:missing_transition:{last_transition_id}"
    return None


def mutate_loop_state(
    target_repo: Path,
    run_id: str,
    event_type: str,
    details: dict[str, Any],
    mutator,
    *,
    node_id: str | None = None,
    subagent_id: str | None = None,
    resource_id: str | None = None,
) -> dict[str, Any]:
    with run_lock(target_repo, run_id):
        state = load_loop_state(target_repo, run_id)
        if not state:
            raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
        block_reason = audit_block_reason(target_repo, run_id, state)
        if block_reason:
            raise RuntimeError(block_reason)
        before_hash = data_hash(state)
        transition_id = details.get("transition_id") if isinstance(details.get("transition_id"), str) else f"tr-{uuid.uuid4().hex}"
        new_state = deepcopy(state)
        mutator(new_state)
        new_state["updated_at"] = utc_now()
        new_state["last_transition_id"] = transition_id
        after_hash = data_hash(new_state)
        append_journal_event(
            target_repo,
            run_id,
            event_type,
            details={**details, "transition_id": transition_id},
            transition_id=transition_id,
            node_id=node_id,
            subagent_id=subagent_id,
            resource_id=resource_id,
            before_hash=before_hash,
            after_hash=after_hash,
        )
        atomic_write_json(loop_state_path(target_repo, run_id), new_state)
        verified = load_loop_state(target_repo, run_id)
        if data_hash(verified) != after_hash:
            raise RuntimeError("loop-state.json verification failed after transition write")
        return verified


def set_active_run(
    target_repo: Path,
    run_id: str,
    phase: str,
    status: str = "active",
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "phase": phase,
        "status": status,
        "updated_at": utc_now(),
        "target_repository": str(target_repo.resolve()),
    }
    atomic_write_json(active_run_path(target_repo), payload)
    return payload


def load_active_run(target_repo: Path) -> dict[str, Any] | None:
    value = load_json_if_exists(active_run_path(target_repo))
    return value if isinstance(value, dict) else None


def validate_active_run_contract(active: dict[str, Any]) -> str | None:
    required = ("run_id", "phase", "status", "updated_at", "target_repository")
    for key in required:
        if key not in active:
            return f"{key}_missing"
    if "schema_version" in active and active.get("schema_version") != 1:
        return "schema_version_invalid"
    for key in required:
        if not isinstance(active.get(key), str) or not active[key].strip():
            return f"{key}_invalid"
    return None


def clear_active_run(target_repo: Path, run_id: str) -> None:
    current = load_active_run(target_repo)
    if not current or current.get("run_id") != run_id:
        return
    path = active_run_path(target_repo)
    if path.exists():
        path.unlink()


def start_phase(
    target_repo: Path,
    run_id: str,
    phase: str,
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    previous = load_loop_state(target_repo, run_id)
    completed_phases = previous.get("completed_phases", {}) if isinstance(previous, dict) else {}
    if not isinstance(completed_phases, dict):
        completed_phases = {}
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "active": True,
        "phase": phase,
        "phase_status": "running",
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
        "run_outcome": None,
        "completion_audit": None,
        "state": initial_state or {},
        "completed_phases": completed_phases,
    }
    atomic_write_json(loop_state_path(target_repo, run_id), payload)
    set_active_run(target_repo, run_id, phase, "active")
    return payload


def load_loop_state(target_repo: Path, run_id: str) -> dict[str, Any] | None:
    value = load_json_if_exists(loop_state_path(target_repo, run_id))
    return value if isinstance(value, dict) else None


def write_loop_state(target_repo: Path, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = utc_now()
    atomic_write_json(loop_state_path(target_repo, run_id), state)
    return state


def update_phase_state(target_repo: Path, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    phase_state = state.setdefault("state", {})
    if not isinstance(phase_state, dict):
        raise ValueError("loop-state.json state must be an object")
    phase_state.update(patch)
    return write_loop_state(target_repo, run_id, state)


def record_node_state(target_repo: Path, run_id: str, node_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    phase_state = state.setdefault("state", {})
    nodes = phase_state.setdefault("nodes", {})
    current = nodes.setdefault(node_id, {})
    current.update(patch)
    current.setdefault("id", node_id)
    current["updated_at"] = utc_now()
    return write_loop_state(target_repo, run_id, state)


def has_substantive_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return bool(value)
    return value is True


def completion_audit_passes(audit: Any) -> bool:
    if not isinstance(audit, dict):
        return False
    if audit.get("passed") is not True:
        return False
    checklist = (
        audit.get("prompt_to_artifact_checklist")
        or audit.get("promptToArtifactChecklist")
        or audit.get("checklist")
        or audit.get("requirements_checklist")
    )
    evidence = (
        audit.get("verification_evidence")
        or audit.get("verificationEvidence")
        or audit.get("evidence")
        or audit.get("validation_evidence")
        or audit.get("commands")
        or audit.get("tests")
    )
    return has_substantive_value(checklist) and has_substantive_value(evidence)


def terminal_reason_present(state: dict[str, Any]) -> bool:
    return any(
        has_substantive_value(state.get(key))
        for key in ("cancellation_reason", "blocked_reason", "failure_reason", "error", "run_outcome")
    )


def open_work_ids(phase_state: dict[str, Any], section: str = "work") -> list[str]:
    items = phase_state.get(section) if isinstance(phase_state.get(section), dict) else {}
    return sorted(
        str(item_id)
        for item_id, record in items.items()
        if not isinstance(record, dict) or not is_terminal_status(record.get("status"))
    )


def active_lease_ids(phase_state: dict[str, Any]) -> list[str]:
    resources = phase_state.get("resources") if isinstance(phase_state.get("resources"), dict) else {}
    leases = resources.get("leases") if isinstance(resources.get("leases"), dict) else {}
    return sorted(
        str(lease_id)
        for lease_id, lease in leases.items()
        if not isinstance(lease, dict) or str(lease.get("status") or "acquired") in {"acquired", "running"}
    )


def evaluate_research_state(state: dict[str, Any]) -> CompletionResult:
    """Research-to-review readiness of a loop-state document (docs/SCHEMA.md section 3.3)."""
    phase_state = state.get("state")
    if not isinstance(phase_state, dict):
        return CompletionResult(False, "research_state_missing", state)
    baseline = phase_state.get("baseline") if isinstance(phase_state.get("baseline"), dict) else {}
    if baseline.get("required") is True and str(baseline.get("status") or "") not in BASELINE_READY_STATUSES:
        return CompletionResult(False, "research_baseline_not_ready", state)
    open_work = open_work_ids(phase_state, "work")
    if open_work:
        return CompletionResult(False, f"research_work_unresolved:{','.join(open_work)}", state)
    open_tasks = open_work_ids(phase_state, "tasks")
    if open_tasks:
        return CompletionResult(False, f"research_tasks_unresolved:{','.join(open_tasks)}", state)
    active_leases = active_lease_ids(phase_state)
    if active_leases:
        return CompletionResult(False, f"research_resources_unresolved:{','.join(active_leases)}", state)
    open_queue = open_resource_queue_ids(phase_state)
    if open_queue:
        return CompletionResult(False, f"research_resource_queue_unresolved:{','.join(open_queue)}", state)
    selection = phase_state.get("selection")
    if not isinstance(selection, dict) or selection.get("status") != "final":
        return CompletionResult(False, "research_selection_not_final", state)
    selected_node = selection.get("selected_node")
    if not has_substantive_value(selected_node):
        return CompletionResult(False, "research_selected_node_missing", state)
    nodes = phase_state.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return CompletionResult(False, "research_nodes_missing", state)
    if selected_node not in nodes:
        return CompletionResult(False, "research_selected_node_not_in_state", state)
    selected = nodes[selected_node]
    if not isinstance(selected, dict):
        return CompletionResult(False, f"research_node_state_invalid:{selected_node}", state)
    if selected.get("status") != "accepted":
        return CompletionResult(False, "research_selected_node_not_accepted", state)
    return CompletionResult(True, "research_state_complete", state)


def evaluate_loop_state_completion(state: dict[str, Any]) -> CompletionResult:
    if state.get("active") is True:
        return CompletionResult(False, "loop_state_active", state)
    phase_status = str(state.get("phase_status") or "")
    if phase_status not in TERMINAL_PHASE_STATUSES:
        return CompletionResult(False, "loop_state_not_terminal", state)
    if phase_status == "blocked":
        present = has_substantive_value(state.get("blocked_reason"))
        return CompletionResult(present, "blocked_reason_present" if present else "blocked_missing_reason", state)
    if phase_status == "cancelled":
        present = terminal_reason_present(state)
        return CompletionResult(present, "cancelled_reason_present" if present else "cancelled_missing_reason", state)
    phase = state.get("phase")
    if phase == "research":
        if phase_status == "exhausted":
            return CompletionResult(False, "research_exhausted_no_selection", state)
        return evaluate_research_state(state)
    if not completion_audit_passes(state.get("completion_audit")):
        return CompletionResult(False, "completion_audit_missing_or_not_passing", state)
    return CompletionResult(True, "completion_audit_passed", state)


def evaluate_completion(target_repo: Path, run_id: str, phase: str | None = None) -> CompletionResult:
    state = load_loop_state(target_repo, run_id)
    if not state:
        return CompletionResult(False, "missing_loop_state", None)
    if phase is None or state.get("phase") == phase:
        return evaluate_loop_state_completion(state)
    completed_phases = state.get("completed_phases")
    if isinstance(completed_phases, dict):
        phase_state = completed_phases.get(phase)
        if isinstance(phase_state, dict):
            return evaluate_loop_state_completion(phase_state)
    return CompletionResult(False, f"missing_completed_phase:{phase}", state)


def phase_gate(phase: str) -> str | None:
    if phase == "research":
        return "research_to_review"
    if phase == "writeup":
        return "launch"
    return None


def has_release_evidence(target_repo: Path, run_id: str, phase: str) -> bool:
    gate = phase_gate(phase)
    if gate is None:
        return True
    return journal_has_event(target_repo, run_id, "validation", gate=gate, exit_code=0) and journal_has_event(
        target_repo,
        run_id,
        "handoff",
        gate=gate,
        approved=True,
        exit_code=0,
    )


def complete_phase(
    target_repo: Path,
    run_id: str,
    completion_audit: dict[str, Any],
    *,
    clear_active: bool = True,
    active_status: str | None = None,
) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    state["active"] = False
    state["phase_status"] = "complete"
    state["completed_at"] = utc_now()
    state["completion_audit"] = completion_audit
    completed_phases = state.setdefault("completed_phases", {})
    if isinstance(completed_phases, dict):
        completed_phases[str(state.get("phase") or "unknown")] = {
            key: value
            for key, value in state.items()
            if key != "completed_phases"
        }
    write_loop_state(target_repo, run_id, state)
    if clear_active:
        clear_active_run(target_repo, run_id)
    else:
        set_active_run(target_repo, run_id, str(state.get("phase") or "unknown"), active_status or "active")
    return state


def exhaust_phase(target_repo: Path, run_id: str, reason: str, completion_audit: dict[str, Any]) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    state["active"] = False
    state["phase_status"] = "exhausted"
    state["run_outcome"] = "exhausted"
    state["exhaustion_reason"] = reason
    state["completed_at"] = utc_now()
    state["completion_audit"] = completion_audit
    completed_phases = state.setdefault("completed_phases", {})
    if isinstance(completed_phases, dict):
        completed_phases[str(state.get("phase") or "unknown")] = {
            key: value
            for key, value in state.items()
            if key != "completed_phases"
        }
    write_loop_state(target_repo, run_id, state)
    clear_active_run(target_repo, run_id)
    return state


def cancel_phase(target_repo: Path, run_id: str, reason: str) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    state["active"] = False
    state["phase_status"] = "cancelled"
    state["run_outcome"] = "cancelled"
    state["cancellation_reason"] = reason
    state["completed_at"] = utc_now()
    write_loop_state(target_repo, run_id, state)
    clear_active_run(target_repo, run_id)
    return state

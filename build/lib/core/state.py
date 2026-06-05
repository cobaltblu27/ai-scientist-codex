#!/usr/bin/env python3
"""State helpers for AI Scientist continuation and Stop-hook gates."""
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

TERMINAL_PHASE_STATUSES = {
    "complete",
    "completed",
    "completed_budget_exhausted",
    "cancelled",
    "blocked_on_user",
    "failed",
    "exhausted",
    "exhausted_no_candidate",
}
ALLOW_WITH_REASON_STATUSES = {"cancelled", "blocked_on_user", "failed"}
JOURNAL_EVENT_TYPES = {
    "state_transition",
    "api_call",
    "stop_hook",
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
}
IDEA_TERMINAL_STATUSES = {
    "accepted",
    "accepted_without_reference",
    "error",
    "exhausted",
    "failed",
    "finalized",
    "skipped",
}
NODE_RESOLVED_STATUSES = {"accepted", "invalid", "rejected"}
NODE_UNRESOLVED_STATUSES = {"planning", "planned", "implementing", "running", "validating", "buggy", "repairing", "candidate"}
NODE_TERMINAL_CRITIC_VERDICTS = {"accepted": "ACCEPT_FINAL", "invalid": "INVALID", "rejected": "KILL"}
NODE_ACCEPTING_CRITIC_VERDICTS = {"ACCEPT_FINAL", "ACCEPT"}
NODE_EVIDENCE_ADMIN_KEYS = {
    "status",
    "updated_at",
    "critic_ref",
    "critic_id",
    "critic_role",
    "critic_verdict",
    "critic_completed_at",
    "critic_evidence_fingerprint",
    "critic_result_path",
    "critic_reviews",
    "node_evidence_fingerprint",
    "rejection_reason",
    "acceptance_rationale",
    "revision_reason",
    "reason",
    "open_repair_id",
    "requires_worker_repair",
    "repair_result_path",
    "required_revisions",
    "last_repair_id",
    "last_repair_completed_at",
    "repair_payload_ref",
    "repair_log_ref",
    "requires_fresh_critic",
}
SUBAGENT_TERMINAL_STATUSES = {"integrated", "rejected_with_reason", "abandoned_with_reason"}
RESOURCE_TERMINAL_STATUSES = {"completed", "cancelled", "superseded", "abandoned", "expired"}


@dataclass(frozen=True)
class CompletionResult:
    complete: bool
    reason: str
    state: dict[str, Any] | None = None


@dataclass(frozen=True)
class StopDecision:
    decision: str
    reason: str
    system_message: str = ""
    run_id: str | None = None
    phase: str | None = None
    state_path: str | None = None

    def to_hook_output(self) -> dict[str, Any]:
        if self.decision == "allow":
            return {}
        output = {
            "decision": "block",
            "reason": self.reason,
            "stopReason": self.reason,
        }
        if self.system_message:
            output["systemMessage"] = self.system_message
        return output


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
    return run_dir(target_repo, run_id) / "config.json"


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


def node_evidence_payload(node: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key not in NODE_EVIDENCE_ADMIN_KEYS}


def node_evidence_fingerprint(node: dict[str, Any]) -> str:
    return data_hash(node_evidence_payload(node))


def node_fresh_critic_reason(node_id: str, node: dict[str, Any], *, required_verdict: str | None = None, allowed_verdicts: set[str] | None = None) -> str | None:
    critic_ref = node.get("critic_ref")
    if not isinstance(critic_ref, str) or not critic_ref.strip():
        return f"research_node_missing_critic_ref:{node_id}"
    verdict = node.get("critic_verdict")
    if allowed_verdicts is not None and verdict not in allowed_verdicts:
        return f"research_node_critic_verdict_invalid:{node_id}:{verdict}"
    if required_verdict is not None and verdict != required_verdict:
        return f"research_node_critic_verdict_invalid:{node_id}:{verdict}"
    fingerprint = node.get("critic_evidence_fingerprint")
    current_fingerprint = node_evidence_fingerprint(node)
    if not isinstance(fingerprint, str) or fingerprint != current_fingerprint:
        return f"research_node_critic_stale:{node_id}"
    return None


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
    phase_status = str(state.get("phase_status") or "")
    if phase_status == "blocked_manual_recovery":
        reason = state.get("blocked_reason") or "manual recovery required"
        return f"manual_recovery_required:{reason}"
    last_transition_id = state.get("last_transition_id")
    if isinstance(last_transition_id, str) and last_transition_id and not journal_has_transition(target_repo, run_id, last_transition_id):
        return f"state_journal_mismatch:missing_transition:{last_transition_id}"
    return None


def block_for_manual_recovery(target_repo: Path, run_id: str, state: dict[str, Any], reason: str) -> dict[str, Any]:
    before_hash = data_hash(state)
    transition_id = f"tr-{uuid.uuid4().hex}"
    blocked = deepcopy(state)
    blocked["active"] = False
    blocked["phase_status"] = "blocked_manual_recovery"
    blocked["blocked_reason"] = reason
    blocked["updated_at"] = utc_now()
    blocked["last_transition_id"] = transition_id
    after_hash = data_hash(blocked)
    append_journal_event(
        target_repo,
        run_id,
        "state_transition",
        details={"command": "manual recovery block", "reason": reason, "transition_id": transition_id},
        transition_id=transition_id,
        before_hash=before_hash,
        after_hash=after_hash,
    )
    atomic_write_json(loop_state_path(target_repo, run_id), blocked)
    set_active_run(target_repo, run_id, str(blocked.get("phase") or "unknown"), "blocked_manual_recovery")
    return blocked


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
            if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                block_for_manual_recovery(target_repo, run_id, state, block_reason)
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
    codex_session_id: str | None = None,
    codex_thread_id: str | None = None,
) -> dict[str, Any]:
    current = load_active_run(target_repo)
    if current and current.get("run_id") == run_id:
        if codex_session_id is None and isinstance(current.get("codex_session_id"), str):
            codex_session_id = current["codex_session_id"]
        if codex_thread_id is None and isinstance(current.get("codex_thread_id"), str):
            codex_thread_id = current["codex_thread_id"]
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "phase": phase,
        "status": status,
        "updated_at": utc_now(),
        "target_repo": str(target_repo.resolve()),
        "codex_session_id": codex_session_id,
        "codex_thread_id": codex_thread_id,
    }
    atomic_write_json(active_run_path(target_repo), payload)
    return payload


def load_active_run(target_repo: Path) -> dict[str, Any] | None:
    value = load_json_if_exists(active_run_path(target_repo))
    return value if isinstance(value, dict) else None


def validate_active_run_contract(active: dict[str, Any]) -> str | None:
    required = ("schema_version", "run_id", "phase", "status", "updated_at", "target_repo")
    for key in required:
        if key not in active:
            return f"{key}_missing"
    if active.get("schema_version") != 1:
        return "schema_version_invalid"
    for key in ("run_id", "phase", "status", "updated_at", "target_repo"):
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
        "stop_policy": "block_until_completion_audit",
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


def record_idea_state(target_repo: Path, run_id: str, idea_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    phase_state = state.setdefault("state", {})
    idea_states = phase_state.setdefault("idea_states", {})
    current = idea_states.setdefault(idea_id, {})
    current.update(patch)
    current.setdefault("id", idea_id)
    current["updated_at"] = utc_now()
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


def mark_buggy_node(target_repo: Path, run_id: str, node_id: str, failure: dict[str, Any]) -> dict[str, Any]:
    patch = {
        "status": "buggy",
        "retryable": failure.get("retryable", True),
        "failure_signature": failure.get("failure_signature") or failure.get("error") or "unknown_failure",
        "last_command": failure.get("last_command"),
        "last_exit_code": failure.get("last_exit_code"),
        "last_error_path": failure.get("last_error_path"),
        "next_action": failure.get("next_action", "repair"),
    }
    return record_node_state(target_repo, run_id, node_id, patch)


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


def has_int_score(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100


def status_has_reason(value: Any) -> bool:
    return has_substantive_value(value)


def nonterminal_subagents(phase_state: dict[str, Any]) -> list[str]:
    subagents = phase_state.get("subagents")
    if not isinstance(subagents, dict):
        return []
    blocked: list[str] = []
    for subagent_id, subagent in subagents.items():
        if not isinstance(subagent, dict):
            blocked.append(str(subagent_id))
            continue
        if str(subagent.get("status") or "") not in SUBAGENT_TERMINAL_STATUSES:
            blocked.append(str(subagent_id))
    return blocked


def blocking_resources(phase_state: dict[str, Any]) -> list[str]:
    resources = phase_state.get("resources")
    if not isinstance(resources, dict):
        return []
    blocked: list[str] = []
    for section_name in ("queues", "requests", "leases"):
        section = resources.get(section_name)
        if isinstance(section, dict):
            iterable = section.items()
        elif isinstance(section, list):
            iterable = [(str(index), item) for index, item in enumerate(section)]
        else:
            continue
        for item_id, item in iterable:
            if not isinstance(item, dict):
                continue
            if item.get("blocking") is False:
                continue
            status = str(item.get("status") or "").lower()
            if status not in RESOURCE_TERMINAL_STATUSES:
                blocked.append(f"{section_name}:{item_id}")
    return blocked


def node_metrics_score(node: dict[str, Any]) -> float | None:
    metrics = node.get("metrics")
    if isinstance(metrics, dict) and "score" in metrics:
        try:
            return float(metrics["score"])
        except (TypeError, ValueError):
            return None
    return None


def validate_node_contract(node_id: str, node: dict[str, Any], official_status: str | None = None) -> str | None:
    if node.get("node_id") != node_id:
        return "node_id_mismatch"
    if official_status and node.get("status") != official_status:
        return "status_mismatch"
    if not has_substantive_value(node.get("benchmark_contract_version")):
        return "benchmark_contract_version_missing"
    if "metrics" not in node and not has_substantive_value(node.get("metrics_ref")):
        return "metrics_missing"
    split = node.get("split_integrity")
    if not isinstance(split, dict) or split.get("pass") is not True:
        return "split_integrity_not_passing"
    leakage = node.get("leakage_check")
    if not isinstance(leakage, dict) or leakage.get("pass") is not True:
        return "leakage_check_not_passing"
    if not has_substantive_value(node.get("result_summary")):
        return "result_summary_missing"
    if not has_substantive_value(node.get("mode_deliverables")):
        return "mode_deliverables_missing"
    trials = node.get("trials")
    if not isinstance(trials, list) or not trials:
        return "trials_missing"
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            return f"trial_invalid:{index}"
        for key in ("trial_id", "purpose", "status", "benchmark_contract_version"):
            if not has_substantive_value(trial.get(key)):
                return f"trial_{key}_missing:{index}"
        if "metrics" not in trial and not has_substantive_value(trial.get("metrics_ref")) and trial.get("purpose") == "benchmark":
            return f"trial_metrics_missing:{index}"
    return None


def evaluate_ideation_state(state: dict[str, Any]) -> CompletionResult:
    phase_state = state.get("state")
    if not isinstance(phase_state, dict):
        return CompletionResult(False, "ideation_state_missing", state)
    required = int(phase_state.get("num_ideas_required") or 0)
    attempted = int(phase_state.get("attempted_slots") or len(phase_state.get("idea_states") or {}) or 0)
    min_candidates = int(phase_state.get("min_candidates_required") or 1)
    idea_states = phase_state.get("idea_states")
    if required <= 0:
        return CompletionResult(False, "ideation_num_ideas_required_missing", state)
    if not isinstance(idea_states, dict):
        return CompletionResult(False, "ideation_idea_states_missing", state)
    if len(idea_states) < attempted:
        return CompletionResult(False, "ideation_attempted_idea_missing", state)
    phase_status = str(state.get("phase_status") or "").lower()
    pending_intents = phase_state.get("pending_intents") if isinstance(phase_state.get("pending_intents"), dict) else {}
    if pending_intents or isinstance(phase_state.get("pending_intent"), dict):
        return CompletionResult(False, "ideation_pending_intent", state)
    active_idea_ids = phase_state.get("active_idea_ids") if isinstance(phase_state.get("active_idea_ids"), list) else []
    if active_idea_ids or phase_state.get("active_idea_id"):
        return CompletionResult(False, "ideation_active_idea_unresolved", state)
    budget_terminal = phase_status == "completed_budget_exhausted"
    if phase_status != "exhausted_no_candidate" and not phase_state.get("early_stop_allowed") and attempted < required:
        return CompletionResult(False, "ideation_not_all_ideas_attempted", state)
    researchable = []
    for idea_id, idea in idea_states.items():
        if not isinstance(idea, dict):
            return CompletionResult(False, f"ideation_idea_state_invalid:{idea_id}", state)
        status = str(idea.get("status") or "")
        if status not in IDEA_TERMINAL_STATUSES:
            return CompletionResult(False, f"ideation_idea_unresolved:{idea_id}", state)
        evaluation = str(idea.get("evaluation") or "").upper()
        if status in {"accepted", "accepted_without_reference", "finalized"} and not idea.get("reflection_count"):
            return CompletionResult(False, f"ideation_accepted_missing_reflection_count:{idea_id}", state)
        if status == "accepted" and not has_int_score(idea.get("score")):
            return CompletionResult(False, f"ideation_accepted_missing_score:{idea_id}", state)
        ranking = phase_state.get("ranking") if isinstance(phase_state.get("ranking"), dict) else {}
        if ranking.get("status") == "final" and status == "accepted" and not isinstance(idea.get("rank"), int):
            return CompletionResult(False, f"ideation_accepted_missing_rank:{idea_id}", state)
        if ranking.get("status") == "final" and evaluation in {"REJECTED", "ACCEPTED_WITHOUT_REFERENCE"} and not has_int_score(idea.get("score")):
            return CompletionResult(False, f"ideation_scored_terminal_missing_score:{idea_id}", state)
        if status in {"skipped", "failed", "error", "exhausted"} and not has_substantive_value(idea.get("skip_reason") or idea.get("reason") or idea.get("error") or idea.get("exhaustion_reason")):
            return CompletionResult(False, f"ideation_skipped_missing_reason:{idea_id}", state)
        if idea.get("researchable") is True or evaluation == "ACCEPTED":
            researchable.append(idea)
    if phase_status == "exhausted_no_candidate":
        if researchable:
            return CompletionResult(False, "ideation_exhausted_has_researchable_candidate", state)
        return CompletionResult(True, "ideation_exhausted_no_candidate_complete", state)
    if phase_status not in {"complete", "completed", "completed_budget_exhausted"}:
        return CompletionResult(False, f"ideation_terminal_status_invalid:{phase_status}", state)
    if budget_terminal and not researchable:
        return CompletionResult(False, "ideation_budget_exhausted_missing_candidate", state)
    if len(researchable) < min_candidates:
        return CompletionResult(False, "ideation_no_researchable_candidate", state)
    handoff = phase_state.get("handoff") if isinstance(phase_state.get("handoff"), dict) else {}
    batch_ids = handoff.get("idea_batch")
    if not isinstance(batch_ids, list) or not batch_ids:
        return CompletionResult(False, "ideation_handoff_batch_missing", state)
    researchable_ids = {str(idea.get("id")) for idea in researchable}
    if any(not isinstance(item, str) or item not in researchable_ids for item in batch_ids):
        return CompletionResult(False, "ideation_handoff_batch_invalid", state)
    return CompletionResult(True, "ideation_state_complete", state)


def evaluate_research_state(state: dict[str, Any]) -> CompletionResult:
    phase_state = state.get("state")
    if not isinstance(phase_state, dict):
        return CompletionResult(False, "research_state_missing", state)
    baseline = phase_state.get("baseline") if isinstance(phase_state.get("baseline"), dict) else {}
    if baseline.get("required") is True and baseline.get("status") != "ready":
        return CompletionResult(False, "research_baseline_not_ready", state)
    work = phase_state.get("work") if isinstance(phase_state.get("work"), dict) else {}
    work_terminal_statuses = {"completed", "cancelled", "failed", "abandoned", "accepted", "rejected"}
    open_work = [
        str(work_id)
        for work_id, record in work.items()
        if not isinstance(record, dict) or str(record.get("status") or "") not in work_terminal_statuses
    ]
    if open_work:
        return CompletionResult(False, f"research_work_unresolved:{','.join(sorted(open_work))}", state)
    tasks = phase_state.get("tasks") if isinstance(phase_state.get("tasks"), dict) else {}
    task_terminal_statuses = work_terminal_statuses
    open_tasks = [
        str(task_id)
        for task_id, task in tasks.items()
        if not isinstance(task, dict) or str(task.get("status") or "") not in task_terminal_statuses
    ]
    if open_tasks:
        return CompletionResult(False, f"research_tasks_unresolved:{','.join(sorted(open_tasks))}", state)
    resources = phase_state.get("resources") if isinstance(phase_state.get("resources"), dict) else {}
    leases = resources.get("leases") if isinstance(resources.get("leases"), dict) else {}
    active_leases = [
        str(lease_id)
        for lease_id, lease in leases.items()
        if not isinstance(lease, dict) or str(lease.get("status") or "acquired") in {"acquired", "running"}
    ]
    if active_leases:
        return CompletionResult(False, f"research_resources_unresolved:{','.join(sorted(active_leases))}", state)
    selection = phase_state.get("selection")
    if not isinstance(selection, dict) or selection.get("status") != "final":
        return CompletionResult(False, "research_selection_not_final", state)
    selected_node = selection.get("selected_node") or phase_state.get("selected_node") or state.get("selected_node")
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
    critic_reason = node_fresh_critic_reason(str(selected_node), selected, allowed_verdicts=NODE_ACCEPTING_CRITIC_VERDICTS)
    if critic_reason:
        return CompletionResult(False, critic_reason, state)
    if selection.get("selected_node") != selected_node:
        return CompletionResult(False, "research_selection_missing_or_stale", state)
    return CompletionResult(True, "research_state_complete", state)


def evaluate_loop_state_completion(state: dict[str, Any]) -> CompletionResult:
    if state.get("active") is True:
        return CompletionResult(False, "loop_state_active", state)
    phase_status = str(state.get("phase_status") or "").lower()
    if phase_status in ALLOW_WITH_REASON_STATUSES:
        return CompletionResult(terminal_reason_present(state), f"{phase_status}_reason_present" if terminal_reason_present(state) else f"{phase_status}_missing_reason", state)
    if phase_status not in TERMINAL_PHASE_STATUSES:
        return CompletionResult(False, "loop_state_not_terminal", state)
    if not completion_audit_passes(state.get("completion_audit")):
        return CompletionResult(False, "completion_audit_missing_or_not_passing", state)
    phase = state.get("phase")
    if phase == "ideation":
        return evaluate_ideation_state(state)
    if phase == "research":
        return evaluate_research_state(state)
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
    if phase == "ideation":
        return "ideation_to_research"
    if phase == "research":
        return "research_to_review"
    if phase == "writeup":
        return "launch"
    return None


def has_stop_release_evidence(target_repo: Path, run_id: str, phase: str) -> bool:
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


def reopen_for_verification(target_repo: Path, run_id: str, reason: str) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not state:
        raise FileNotFoundError(f"missing loop-state.json for run {run_id}")
    state["active"] = True
    state["phase_status"] = "verifying"
    state["reopened_by_stop_hook"] = True
    state["reopen_reason"] = reason
    state["completed_at"] = None
    write_loop_state(target_repo, run_id, state)
    set_active_run(target_repo, run_id, str(state.get("phase") or "unknown"), "active")
    return state


def resolve_target_repo_from_payload(payload: dict[str, Any], cwd: Path | None = None) -> Path:
    candidates = [
        payload.get("cwd"),
        payload.get("working_directory"),
        payload.get("workingDirectory"),
        payload.get("workspace_root"),
        payload.get("workspaceRoot"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return Path(candidate).resolve()
    return (cwd or Path.cwd()).resolve()


def payload_identity_value(payload: dict[str, Any], keys: tuple[str, ...], env_keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in env_keys:
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def stop_caller_identity(payload: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    payload = payload or {}
    session_id = payload_identity_value(
        payload,
        ("codex_session_id", "codexSessionId", "session_id", "sessionId"),
        ("CODEX_SESSION_ID", "CODEX_SESSION"),
    )
    thread_id = payload_identity_value(
        payload,
        ("codex_thread_id", "codexThreadId", "thread_id", "threadId"),
        ("CODEX_THREAD_ID", "CODEX_THREAD"),
    )
    return session_id, thread_id


def stop_is_worker_context(payload: dict[str, Any] | None = None) -> bool:
    payload = payload or {}
    marker = payload.get("ai_scientist_worker") or payload.get("aiScientistWorker")
    if marker is True or (isinstance(marker, str) and marker.strip().lower() in {"1", "true", "yes"}):
        return True
    return os.environ.get("AI_SCIENTIST_WORKER", "").strip().lower() in {"1", "true", "yes"}


def active_run_owned_by_caller(active: dict[str, Any], payload: dict[str, Any] | None = None) -> bool | None:
    owner_session = active.get("codex_session_id")
    owner_thread = active.get("codex_thread_id")
    has_owner = isinstance(owner_session, str) and bool(owner_session.strip()) or isinstance(owner_thread, str) and bool(owner_thread.strip())
    if not has_owner:
        return None
    caller_session, caller_thread = stop_caller_identity(payload)
    if isinstance(owner_session, str) and owner_session.strip() and caller_session == owner_session.strip():
        return True
    if isinstance(owner_thread, str) and owner_thread.strip() and caller_thread == owner_thread.strip():
        return True
    if caller_session or caller_thread:
        return False
    return True


def evaluate_stop_decision(target_repo: Path, payload: dict[str, Any] | None = None) -> StopDecision:
    active = load_active_run(target_repo)
    if not active:
        return StopDecision("allow", "no_active_ai_scientist_run")
    active_reason = validate_active_run_contract(active)
    if active_reason:
        return StopDecision("block", f"active_run_invalid:{active_reason}", "AI Scientist active-run.json is malformed; repair it before stopping.")
    run_id = active.get("run_id")
    phase = active.get("phase")
    if not isinstance(run_id, str) or not run_id.strip():
        return StopDecision("block", "active_run_missing_run_id", "AI Scientist active-run.json is malformed; repair it before stopping.")
    state_path = loop_state_path(target_repo, run_id)
    state = load_loop_state(target_repo, run_id)
    if not state:
        return StopDecision("block", "missing_loop_state", f"AI Scientist active run {run_id} has no loop-state.json. Restore state or cancel explicitly before stopping.", run_id, phase, str(state_path))
    phase = str(state.get("phase") or phase or "unknown")
    if active.get("status") == "validating":
        message = f"AI Scientist {phase} is validating run {run_id}. Continue until validation clears active-run.json."
        return StopDecision("block", f"ai_scientist_{phase}_validating", message, run_id, phase, str(state_path))
    if state.get("active") is True:
        if phase == "research" and stop_is_worker_context(payload):
            return StopDecision("allow", "ai_scientist_research_worker_stop_ignored", run_id=run_id, phase=phase, state_path=str(state_path))
        if phase == "research" and active_run_owned_by_caller(active, payload) is False:
            return StopDecision("allow", "ai_scientist_research_non_orchestrator_stop_ignored", run_id=run_id, phase=phase, state_path=str(state_path))
        phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
        cursor = ""
        if phase in {"research", "writeup"}:
            orchestrator = phase_state.get("orchestrator") if isinstance(phase_state.get("orchestrator"), dict) else {}
            next_action = orchestrator.get("next_action")
            details = orchestrator.get("next_action_details") if isinstance(orchestrator.get("next_action_details"), dict) else {}
            current_node = orchestrator.get("current_node") or phase_state.get("current_node") or phase_state.get("selected_node")
            if next_action:
                reason = details.get("reason") or details.get("audit_verdict")
                cursor = f" Run: {run_id}. Next action: {next_action}."
                if current_node:
                    cursor += f" Node: {current_node}."
                pending_audit = details.get("pending_audit")
                if pending_audit:
                    cursor += f" Pending audit: {pending_audit}."
                if reason:
                    cursor += f" Reason: {reason}."
        elif phase == "ideation":
            try:
                from ideation.state import current_config, cursor_for_state

                ideation_cursor = cursor_for_state(state, current_config(target_repo, run_id))
            except Exception:
                ideation_cursor = {}
            next_action = ideation_cursor.get("next_action")
            details = ideation_cursor.get("next_action_details") if isinstance(ideation_cursor.get("next_action_details"), dict) else {}
            if next_action:
                cursor = f" Run: {run_id}. Next action: {next_action}."
                idea_id = details.get("idea_id") or details.get("next_idea_id")
                intent_id = details.get("intent_id")
                pending_count = details.get("pending_count")
                intent_ids = details.get("intent_ids") if isinstance(details.get("intent_ids"), list) else []
                reason = details.get("reason")
                if idea_id:
                    cursor += f" Idea: {idea_id}."
                if intent_id:
                    cursor += f" Intent: {intent_id}."
                if pending_count:
                    cursor += f" Pending intents: {pending_count}."
                if intent_ids:
                    cursor += f" Representative intents: {', '.join(str(item) for item in intent_ids[:5])}."
                if reason:
                    cursor += f" Reason: {reason}."
        else:
            idea_index = phase_state.get("current_idea_index")
            reflection_round = phase_state.get("current_reflection_round")
            idea_states = phase_state.get("idea_states") if isinstance(phase_state.get("idea_states"), dict) else {}
            idea_id = f"idea-{int(idea_index):03d}" if isinstance(idea_index, int) and idea_index > 0 else None
            idea_state = idea_states.get(idea_id, {}) if idea_id else {}
            if idea_id:
                cursor = f" Run: {run_id}. Idea: {idea_id}. Round: {reflection_round}. Status: {idea_state.get('status', state.get('phase_status'))}."
        if not cursor:
            cursor = f" Run: {run_id}. Status: {state.get('phase_status', 'active')}."
        message = f"AI Scientist {phase} is still active.{cursor} Continue from {state_path} and do not report completion until completion_audit passes."
        return StopDecision("block", f"ai_scientist_{phase}_active", message, run_id, phase, str(state_path))
    result = evaluate_completion(target_repo, run_id)
    phase_status = str(state.get("phase_status") or "").lower()
    if result.complete:
        if phase_status in ALLOW_WITH_REASON_STATUSES and terminal_reason_present(state):
            return StopDecision("allow", f"{phase_status}_with_reason", run_id=run_id, phase=phase, state_path=str(state_path))
        if phase == "ideation" and phase_status == "exhausted_no_candidate":
            return StopDecision("allow", "ideation_exhausted_no_candidate", run_id=run_id, phase=phase, state_path=str(state_path))
        if not has_stop_release_evidence(target_repo, run_id, phase):
            message = f"AI Scientist {phase} completion state is complete but validation/handoff journal evidence is missing. Continue verification before stopping."
            return StopDecision("block", f"ai_scientist_{phase}_missing_release_evidence", message, run_id, phase, str(state_path))
        return StopDecision("allow", result.reason, run_id=run_id, phase=phase, state_path=str(state_path))
    if phase_status in ALLOW_WITH_REASON_STATUSES and terminal_reason_present(state):
        return StopDecision("allow", f"{phase_status}_with_reason", run_id=run_id, phase=phase, state_path=str(state_path))
    if phase_status in TERMINAL_PHASE_STATUSES or phase_status == "verifying":
        reopen_for_verification(target_repo, run_id, result.reason)
        message = f"AI Scientist {phase} completion audit is incomplete ({result.reason}). Continue verification and update completion_audit before stopping."
        return StopDecision("block", f"ai_scientist_{phase}_completion_audit_blocked", message, run_id, phase, str(state_path))
    message = f"AI Scientist {phase} is not terminal ({phase_status or 'unknown'}). Continue the phase before stopping."
    return StopDecision("block", f"ai_scientist_{phase}_not_terminal", message, run_id, phase, str(state_path))


def log_stop_decision(target_repo: Path, decision: StopDecision, payload: dict[str, Any] | None = None) -> None:
    if not decision.run_id:
        return
    append_journal_event(
        target_repo,
        decision.run_id,
        "stop_hook",
        details={
            "phase": decision.phase,
            "decision": decision.decision,
            "reason": decision.reason,
            "state_path": decision.state_path,
            "hook_event_name": (payload or {}).get("hook_event_name") or (payload or {}).get("hookEventName"),
        },
    )

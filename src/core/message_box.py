"""Message box: human steering messages for a research run.

One JSON file per message under `runs/<run-id>/message-box/`. The dashboard
(or `ai-scientist message-box add`) creates a message targeting one node; the
orchestrator lists pending messages at every sweep and records what it did with
`ai-scientist message-box update`. Shape: docs/SCHEMA.md section 3.11.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.state import append_journal_event, atomic_write_json, load_json_if_exists, run_dir

DIR_NAME = "message-box"
KINDS = {"revision", "branch"}
STATUSES = ("pending", "acknowledged", "completed", "rejected", "cancelled")
TRANSITIONS: dict[str, set[str]] = {
    "pending": {"acknowledged", "rejected", "cancelled"},
    "acknowledged": {"completed", "rejected", "cancelled"},
    "completed": set(),
    "rejected": set(),
    "cancelled": set(),
}
MAX_PROMPT_CHARS = 20_000


class MessageBoxError(ValueError):
    pass


def message_box_dir(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / DIR_NAME


def message_path(target_repo: Path, run_id: str, message_id: str) -> Path:
    if not message_id or "/" in message_id or message_id in {".", ".."}:
        raise MessageBoxError(f"invalid message id: {message_id!r}")
    return message_box_dir(target_repo, run_id) / f"{message_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(now: str) -> str:
    compact = now.replace("-", "").replace(":", "")
    return f"msg-{compact}-{secrets.token_hex(2)}"


def _known_nodes(target_repo: Path, run_id: str) -> set[str] | None:
    """Node ids in loop-state.state.nodes, or None when the ledger cannot be read."""
    state = load_json_if_exists(run_dir(target_repo, run_id) / "loop-state.json") if (run_dir(target_repo, run_id) / "loop-state.json").exists() else None
    if not isinstance(state, dict):
        return None
    nodes = (state.get("state") or {}).get("nodes") if isinstance(state.get("state"), dict) else None
    if not isinstance(nodes, dict):
        return None
    return {str(k) for k in nodes}


def add(target_repo: Path, run_id: str, node_id: str, kind: str, prompt: str) -> dict[str, Any]:
    run = run_dir(target_repo, run_id)
    if not run.is_dir():
        raise MessageBoxError(f"unknown run: {run_id}")
    if kind not in KINDS:
        raise MessageBoxError(f"kind must be one of {', '.join(sorted(KINDS))} (got {kind!r})")
    node_id = (node_id or "").strip()
    if not node_id:
        raise MessageBoxError("node_id is required")
    prompt = (prompt or "").strip()
    if not prompt:
        raise MessageBoxError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise MessageBoxError(f"prompt longer than {MAX_PROMPT_CHARS} characters")
    known = _known_nodes(target_repo, run_id)
    if known is not None and node_id not in known:
        raise MessageBoxError(f"unknown node: {node_id}")
    now = _now()
    record = {
        "id": _new_id(now),
        "run_id": run_id,
        "node_id": node_id,
        "kind": kind,
        "prompt": prompt,
        "created_at": now,
        "status": "pending",
        "updated_at": now,
        "work_id": None,
        "result_node_id": None,
        "note": None,
    }
    atomic_write_json(message_path(target_repo, run_id, record["id"]), record)
    append_journal_event(
        target_repo,
        run_id,
        "message",
        node_id=node_id,
        details={"command": "message-box add", "message_id": record["id"], "kind": kind, "status": "pending"},
    )
    return record


def load(target_repo: Path, run_id: str, message_id: str) -> dict[str, Any]:
    path = message_path(target_repo, run_id, message_id)
    if not path.is_file():
        raise MessageBoxError(f"unknown message: {message_id}")
    data = load_json_if_exists(path)
    if not isinstance(data, dict):
        raise MessageBoxError(f"malformed message file: {path.name}")
    return data


def list_messages(target_repo: Path, run_id: str, *, status: str | None = None, node_id: str | None = None) -> list[dict[str, Any]]:
    """Every readable message, oldest first. Malformed files are skipped."""
    box = message_box_dir(target_repo, run_id)
    if not box.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(box.glob("*.json")):
        try:
            data = load_json_if_exists(path)
        except ValueError:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            continue
        if status and data.get("status") != status:
            continue
        if node_id and data.get("node_id") != node_id:
            continue
        out.append(data)
    out.sort(key=lambda m: (str(m.get("created_at") or ""), str(m.get("id"))))
    return out


def update(
    target_repo: Path,
    run_id: str,
    message_id: str,
    status: str,
    *,
    work_id: str | None = None,
    result_node_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise MessageBoxError(f"status must be one of {', '.join(STATUSES)} (got {status!r})")
    record = load(target_repo, run_id, message_id)
    current = str(record.get("status") or "pending")
    if status not in TRANSITIONS.get(current, set()):
        raise MessageBoxError(f"cannot move message {message_id} from {current} to {status}")
    if status == "acknowledged" and not work_id and not record.get("work_id"):
        raise MessageBoxError("acknowledged requires --work-id")
    if status == "rejected" and not note:
        raise MessageBoxError("rejected requires --note")
    record["status"] = status
    record["updated_at"] = _now()
    if work_id is not None:
        record["work_id"] = work_id
    if result_node_id is not None:
        record["result_node_id"] = result_node_id
    if note is not None:
        record["note"] = note
    atomic_write_json(message_path(target_repo, run_id, message_id), record)
    details: dict[str, Any] = {"command": "message-box update", "message_id": message_id, "status": status}
    if work_id:
        details["work_id"] = work_id
    if result_node_id:
        details["result_node_id"] = result_node_id
    if note:
        details["note"] = note
    append_journal_event(target_repo, run_id, "message", node_id=str(record.get("node_id") or "") or None, details=details)
    return record

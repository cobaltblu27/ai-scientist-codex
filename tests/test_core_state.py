from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.state import (
    ALLOW_WITH_REASON_STATUSES,
    TERMINAL_PHASE_STATUSES,
    WORK_TERMINAL_STATUSES,
    append_journal_event,
    evaluate_loop_state_completion,
    is_terminal_status,
    load_active_run,
    mutate_loop_state,
    set_active_run,
    validate_active_run_contract,
)
from test_support import write_json


def test_phase_vocabulary_matches_schema_md() -> None:
    assert TERMINAL_PHASE_STATUSES == {"success", "exhausted", "cancelled", "blocked", "complete"}
    assert ALLOW_WITH_REASON_STATUSES == {"cancelled", "blocked"}


def test_work_terminal_set_is_shared() -> None:
    assert WORK_TERMINAL_STATUSES == {"completed", "cancelled", "failed", "abandoned", "accepted", "rejected"}
    for status in WORK_TERMINAL_STATUSES:
        assert is_terminal_status(status)
    for status in ("running", "planned", "candidate", "buggy", "", None):
        assert not is_terminal_status(status)


def test_blocked_requires_blocked_reason() -> None:
    state = {"active": False, "phase": "research", "phase_status": "blocked", "state": {}}
    assert evaluate_loop_state_completion(state).complete is False
    state["blocked_reason"] = "evaluator script missing"
    assert evaluate_loop_state_completion(state).complete is True


def test_active_run_uses_target_repository(tmp_path: Path) -> None:
    payload = set_active_run(tmp_path, "run-1", "research", "active")
    assert payload["target_repository"] == str(tmp_path.resolve())
    assert "target_repo" not in payload
    assert validate_active_run_contract(load_active_run(tmp_path) or {}) is None
    assert validate_active_run_contract({"run_id": "r", "phase": "research", "status": "active", "updated_at": "t", "target_repo": "/x"}) == "target_repository_missing"


def test_state_journal_mismatch_blocks_transition_without_rewriting_state(tmp_path: Path) -> None:
    run = tmp_path / ".ai-scientist" / "runs" / "run-1"
    state = {
        "run_id": "run-1",
        "active": True,
        "phase": "research",
        "phase_status": "running",
        "updated_at": "2026-09-09T00:00:00Z",
        "last_transition_id": "tr-missing",
        "state": {},
    }
    write_json(run / "loop-state.json", state)
    append_journal_event(tmp_path, "run-1", "setup", details={"command": "bootstrap"})
    with pytest.raises(RuntimeError, match="state_journal_mismatch"):
        mutate_loop_state(tmp_path, "run-1", "state_transition", {"command": "test"}, lambda s: None)
    on_disk = json.loads((run / "loop-state.json").read_text())
    assert on_disk["phase_status"] == "running"
    assert on_disk["active"] is True

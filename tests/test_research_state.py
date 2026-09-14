from __future__ import annotations

from core.state import evaluate_loop_state_completion


def completed_research_state(selected_by_ranker: bool = False) -> dict:
    node = {"status": "accepted", "updated_at": "2026-09-09T08:32:23Z"}
    if selected_by_ranker:
        node["latest_ranking_ref"] = "logs/rankings/rank-001/result.md"
    return {
        "active": False,
        "phase": "research",
        "phase_status": "success",
        "run_outcome": "success",
        "state": {
            "orchestrator": {"next_action": "hand off to review"},
            "baseline": {"status": "not_required"},
            "nodes": {"node-001": node},
            "work": {},
            "tasks": {},
            "selection": {"status": "final", "selected_node": "node-001"},
        },
    }


def test_research_completion_does_not_require_ranker_selection() -> None:
    result = evaluate_loop_state_completion(completed_research_state())
    assert result.complete is True


def test_research_completion_treats_ranker_selection_as_allocation_only() -> None:
    result = evaluate_loop_state_completion(completed_research_state(selected_by_ranker=True))
    assert result.complete is True


def test_research_completion_does_not_require_a_completion_audit_object() -> None:
    state = completed_research_state()
    state["state"]["orchestrator"]["completion_audit"] = "logs/completion-audit.md"
    assert evaluate_loop_state_completion(state).complete is True

from __future__ import annotations

from core.state import evaluate_loop_state_completion


def completed_research_state(critic_verdict: str | None = None) -> dict:
    node = {"status": "accepted"}
    if critic_verdict is not None:
        node["critic_verdict"] = critic_verdict
    return {
        "active": False,
        "phase": "research",
        "phase_status": "complete",
        "completion_audit": {
            "passed": True,
            "checklist": ["binding contract criteria satisfied"],
            "evidence": ["metrics.json", "split-integrity.json"],
        },
        "state": {
            "nodes": {"node-001": node},
            "selection": {"status": "final", "selected_node": "node-001"},
        },
    }


def test_research_completion_does_not_require_critic_recommendation() -> None:
    result = evaluate_loop_state_completion(completed_research_state())
    assert result.complete is True


def test_research_completion_treats_critic_recommendation_as_advisory() -> None:
    result = evaluate_loop_state_completion(completed_research_state("KILL"))
    assert result.complete is True

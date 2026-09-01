from __future__ import annotations

from argparse import Namespace

from core.state import evaluate_loop_state_completion
from research.workflow import initial_config
from test_support import read_json, write_json


def completed_research_state(selected_by_ranker: bool = False) -> dict:
    node = {"status": "accepted"}
    if selected_by_ranker:
        node["latest_ranking_ref"] = "logs/rankings/rank-001/result.md"
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


def test_research_completion_does_not_require_ranker_selection() -> None:
    result = evaluate_loop_state_completion(completed_research_state())
    assert result.complete is True


def test_research_completion_treats_ranker_selection_as_allocation_only() -> None:
    result = evaluate_loop_state_completion(completed_research_state(selected_by_ranker=True))
    assert result.complete is True


def test_research_config_uses_shared_ranker(tmp_path) -> None:
    args = Namespace(run_id="ranker-test", selected_idea_id=None)
    payload = {
        "idea_batch": [{"id": "idea-1", "title": "One"}],
        "research_contract": {"success_criteria": {"metric": "score", "minimum": 1.0}},
    }
    cfg = initial_config(tmp_path, args, payload)
    research = cfg["research"]
    assert research["ranker_agent"] == "ai-scientist-research-ranker"
    assert research["ranker_prompt_source"] == "agents/ai-scientist-research-ranker.toml"
    assert research["ranking_top_n"] == 3
    assert research["active_node_cap"] == 3

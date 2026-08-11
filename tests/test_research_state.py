from __future__ import annotations

from argparse import Namespace

from core.state import evaluate_loop_state_completion
from research.workflow import initial_config, migrate_research_ranker_config
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
    args = Namespace(strictness_mode="scientist", run_id="ranker-test", selected_idea_id=None)
    payload = {
        "idea_batch": [{"id": "idea-1", "title": "One"}],
        "research_contract": {"success_criteria": {"metric": "score", "minimum": 1.0}},
    }
    cfg = initial_config(tmp_path, args, payload)
    research = cfg["research"]
    assert research["ranker_agent"] == "ai-scientist-research-ranker"
    assert research["ranker_prompt_source"] == "prompts/research-loop/ranker.md"
    assert research["ranking_top_n"] == 3
    assert research["active_node_cap"] == 3
    assert "critic_agent" not in research


def test_existing_research_config_migrates_from_critic_to_ranker(tmp_path) -> None:
    path = tmp_path / ".ai-scientist" / "runs" / "old-run" / "config.json"
    write_json(
        path,
        {
            "research": {
                "critic_agent": "ai-scientist-research-critic-scientist",
                "critic_prompt_source": "prompts/research-loop/scientist/critic.md",
            }
        },
    )
    assert migrate_research_ranker_config(tmp_path, "old-run", "scientist") is True
    research = read_json(path)["research"]
    assert research["ranker_agent"] == "ai-scientist-research-ranker"
    assert research["ranker_prompt_source"] == "prompts/research-loop/ranker.md"
    assert "critic_agent" not in research
    assert "critic_prompt_source" not in research

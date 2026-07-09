from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_support import read_json

from ideation import state as ideation_state


def campaign_contract() -> dict[str, object]:
    return {
        "primary_hypothesis": "The idea improves the fixed benchmark.",
        "goal_type": "performance",
        "success_criteria": "Improve fixed held-out score by at least 0.03.",
        "failure_criteria": "No improvement after a complete implementation.",
        "allowed_rescue_scope": "Same benchmark only.",
        "kill_criteria": "Stop if the fixed benchmark must change.",
        "non_drift_definition": "Do not change dataset, split, baseline, metric, or evaluator.",
        "metrics_that_matter": ["score"],
        "non_negotiable_comparisons": ["baseline"],
        "baseline_reference": {"title": "Fixture baseline", "usability": "Defines the comparable baseline."},
        "benchmark_plan": "Run fixed evaluator on baseline and candidate.",
        "target_threshold": "Candidate improves by 0.03.",
        "fixed_dataset": "fixture dataset",
        "fixed_split": "fixture split",
        "fixed_baseline": "fixture baseline",
        "evaluator_command": "uv run python -m pytest",
    }


def final_idea() -> dict[str, object]:
    return {
        "id": "idea-001",
        "family_key": "fixture-family",
        "title": "Fixture schema idea",
        "hypothesis": "This intervention improves fixed held-out score over the baseline.",
        "unique_protocol": "Run baseline, apply intervention, compare fixed held-out score.",
        "expected_metric": "score",
        "mechanism": "Improves representation quality under the fixed evaluator.",
        "implementation_sketch": "Modify the existing model update path and run the evaluator.",
        "expected_metric_effect": "Improve held-out score by at least 0.03.",
        "fit_to_research_contract": "Uses the fixed dataset, split, baseline, metric, and evaluator unchanged.",
        "novelty_angle": "Tests a specific mechanism under the repository benchmark.",
        "smoke_runnable_now": True,
        "requires_implementation": [],
        "minimum_command": "uv run python -m pytest",
        "evidence_refs": [],
        "rubric_scores": {"feasibility": 80, "repo_fit": 80},
        "risk_flags": ["May not beat the baseline."],
    }


class IdeationStateTests(unittest.TestCase):
    def test_start_writes_goal_driven_ledger_state(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            state = ideation_state.start_ideation(target, "run-001", "fixture", mode="engineer", payload={"research_contract": campaign_contract()})

            phase_state = state["state"]
            self.assertEqual(phase_state["orchestrator"]["control"], "create_goal")
            self.assertNotIn("reflection_budget_per_idea", phase_state)
            self.assertNotIn("max_attempts_per_slot", phase_state)
            self.assertEqual(ideation_state.cursor_for_state(state)["next_action"], None)
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").exists())

    def test_selector_and_schema_builder_intents_are_ledger_artifacts(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            ideation_state.start_ideation(target, "run-001", "fixture", mode="engineer", payload={"research_contract": campaign_contract()})
            batch = ideation_state.start_intent_batch(target, "run-001", "selector", count=1)
            intent = batch["intents"][0]
            Path(intent["result_path"]).write_text("Select idea-001 because it is feasible.")

            ideation_state.complete_intent(target, "run-001", {}, intent_id=intent["intent_id"])
            state = read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")
            self.assertEqual(state["state"]["pending_intents"], {})
            self.assertEqual(len(state["state"]["artifacts"]["selector_reports"]), 1)

    def test_finalize_ready_and_complete_use_final_schema_only(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            ideation_state.start_ideation(target, "run-001", "fixture", mode="engineer", payload={"research_contract": campaign_contract()})
            ideation_state.finalize_ready(target, "run-001", payload={"ideas": [final_idea()]})
            completed = ideation_state.complete_ideation(target, "run-001")

            self.assertEqual(completed["phase_status"], "COMPLETED")
            ideas = read_json(target / ".ai-scientist" / "runs" / "run-001" / "ideas.json")["ideas"]
            self.assertEqual(ideas[0]["evaluation"], "ACCEPTED")
            self.assertEqual(completed["state"]["handoff"]["idea_batch"], ["idea-001"])


if __name__ == "__main__":
    unittest.main()

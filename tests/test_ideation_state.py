from __future__ import annotations

import json
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


class IdeationStateTests(unittest.TestCase):
    def _start_run_with_drafts(self, target: Path, *, count: int = 1) -> None:
        (target / "README.md").write_text("fixture target\n")
        ideation_state.start_ideation(target, "run-001", "fixture", mode="engineer", num_ideas_required=count, payload={"research_contract": campaign_contract()})
        for index in range(1, count + 1):
            idea_id = f"idea-{index:03d}"
            ideation_state.record_draft(
                target,
                "run-001",
                {
                    "id": idea_id,
                    "title": f"Fixture idea {index}",
                    "hypothesis": "Changing the update rule will improve held-out score.",
                    "fit_to_research_contract": "Uses the fixed benchmark contract unchanged.",
                    "smoke_runnable_now": False,
                },
                idea_id=idea_id,
            )

    def _loop_state(self, target: Path) -> dict:
        return read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")

    def test_explicit_command_detection_only(self) -> None:
        self.assertTrue(ideation_state.is_ideation_command("/ideate propose ideas"))
        self.assertTrue(ideation_state.is_ideation_command("$ai-scientist ideate propose ideas"))
        self.assertTrue(ideation_state.is_ideation_command("ai-scientist: ideate propose ideas"))
        self.assertFalse(ideation_state.is_ideation_command("please brainstorm research ideas"))

    def test_initialize_writes_state_and_artifacts(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            (target / "README.md").write_text("fixture target\n")
            state = ideation_state.initialize_ideation(target, "study benchmark-preserving ideas", run_id="ideation-test", target_num_ideas=2)

            self.assertEqual(state["status"], "active")
            self.assertEqual(state["current_idea_id"], "idea-001")
            self.assertEqual(state["max_stop_continuations"], 12)
            self.assertEqual(state["next_action"]["type"], "propose")
            self.assertTrue((target / ".ai-scientist" / "state" / "active-ideation.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "ideation-test" / "filesystem-baseline.json").exists())
            pointer = read_json(target / ".ai-scientist" / "state" / "active-ideation.json")
            self.assertEqual(pointer["state_file"], ".ai-scientist/runs/ideation-test/ideation-state.json")

    def test_repeated_stop_block_becomes_user_blocker(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(
                target,
                "study ideas",
                run_id="ideation-test",
                max_stop_continuations=10,
                max_repeated_block_count=2,
            )
            state = ideation_state.register_stop_block(target, state, "missing_parseable_action")
            state = ideation_state.register_stop_block(target, state, "missing_parseable_action")
            state = ideation_state.register_stop_block(target, state, "missing_parseable_action")

            self.assertEqual(state["status"], "blocked")
            self.assertEqual(state["reason"], "repeated_stop_hook_block")
            self.assertTrue(state["next_user_action_required"])

    def test_stop_continuation_limit_blocks_cleanly(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(
                target,
                "study ideas",
                run_id="ideation-test",
                max_stop_continuations=2,
            )
            state = ideation_state.register_stop_continuation(target, state)
            state = ideation_state.register_stop_continuation(target, state)
            state = ideation_state.register_stop_continuation(target, state)

            self.assertEqual(state["status"], "blocked")
            self.assertEqual(state["reason"], "max_stop_continuations_exceeded")
            self.assertTrue(state["next_user_action_required"])

    def test_action_snapshot_points_state_to_file(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(target, "study ideas", run_id="ideation-test")
            state, action_path = ideation_state.record_action(
                target,
                state,
                'ACTION:\nFinalizeIdea\nARGUMENTS:\n{"idea": {"title": "Draft"}}',
                {"turn_id": "turn-abc"},
            )

            self.assertTrue(action_path.exists())
            self.assertEqual(state["last_action_file"], "actions/turn-abc-0001.json")
            record = read_json(action_path)
            self.assertEqual(record["parsed_action"]["action"], "FinalizeIdea")

if __name__ == "__main__":
    unittest.main()

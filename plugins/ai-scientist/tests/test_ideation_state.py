from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_support import read_json

import ideation_state


class IdeationStateTests(unittest.TestCase):
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
                'ACTION:\nSearchSemanticScholar\nARGUMENTS:\n{"query": "benchmark preserving ideas"}',
                {"turn_id": "turn-abc"},
            )

            self.assertTrue(action_path.exists())
            self.assertEqual(state["last_action_file"], "actions/turn-abc-0001.json")
            record = read_json(action_path)
            self.assertEqual(record["parsed_action"]["action"], "SearchSemanticScholar")


if __name__ == "__main__":
    unittest.main()

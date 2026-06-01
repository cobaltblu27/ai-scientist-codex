from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_ARGS = ["uv", "run", "--project", str(REPO_ROOT), "ai-scientist"]

from core.state import (
    append_journal_event,
    complete_phase,
    evaluate_stop_decision,
    load_loop_state,
    set_active_run,
    start_phase,
)


class ContinuationStateTests(unittest.TestCase):
    def test_active_ideation_blocks_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start_phase(
                target,
                "run-001",
                "ideation",
                {
                    "num_ideas_required": 1,
                    "num_reflections_required": 1,
                    "finalized_count": 0,
                    "skipped_count": 0,
                    "idea_states": {"idea-001": {"status": "reflecting"}},
                },
            )

            decision = evaluate_stop_decision(target)

            self.assertEqual(decision.decision, "block")
            self.assertIn("active", decision.reason)

    def test_terminal_missing_audit_reopens_and_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            state = start_phase(target, "run-001", "ideation", {})
            state["active"] = False
            state["phase_status"] = "complete"
            state["completion_audit"] = None
            state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            state_path.write_text(json.dumps(state, indent=2) + "\n")

            decision = evaluate_stop_decision(target)
            reopened = load_loop_state(target, "run-001")

            self.assertEqual(decision.decision, "block")
            self.assertEqual(reopened["phase_status"], "verifying")
            self.assertTrue(reopened["active"])

    def test_terminal_passing_audit_allows_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start_phase(
                target,
                "run-001",
                "ideation",
                {
                    "num_ideas_required": 1,
                    "attempted_slots": 1,
                    "min_candidates_required": 1,
                    "active_idea_id": None,
                    "pending_intent": None,
                    "ranking": {"status": "final", "selected_idea_id": "idea-001"},
                    "handoff": {"status": "ready", "selected_idea_id": "idea-001"},
                    "idea_states": {
                        "idea-001": {
                            "id": "idea-001",
                            "status": "accepted",
                            "evaluation": "ACCEPTED",
                            "reflection_count": 1,
                            "score": 90,
                            "rank": 1,
                            "researchable": True,
                        }
                    },
                },
            )
            complete_phase(
                target,
                "run-001",
                {
                    "passed": True,
                    "prompt_to_artifact_checklist": ["idea-001 finalized"],
                    "verification_evidence": ["ideas.json contains idea-001"],
                },
            )
            append_journal_event(target, "run-001", "validation", details={"gate": "ideation_to_research", "exit_code": 0})
            append_journal_event(target, "run-001", "handoff", details={"gate": "ideation_to_research", "approved": True, "exit_code": 0})

            decision = evaluate_stop_decision(target)

            self.assertEqual(decision.decision, "allow")

    def test_stop_hook_outputs_single_json_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start_phase(target, "run-001", "research", {"baseline_status": "running"})
            proc = subprocess.run(
                [
                    *CLI_ARGS,
                    "hooks",
                    "stop-gate",
                    "--target-repo",
                    str(target),
                ],
                input=json.dumps({"hook_event_name": "Stop", "cwd": str(target)}),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0)
            output = json.loads(proc.stdout)
            self.assertEqual(output["decision"], "block")
            self.assertEqual(proc.stdout.count("\n"), 1)
            journal = target / ".ai-scientist" / "runs" / "run-001" / "journal.jsonl"
            self.assertTrue(journal.exists())
            records = [json.loads(line) for line in journal.read_text().splitlines()]
            self.assertEqual(records[-1]["event_type"], "stop_hook")

    def test_research_completion_requires_validation_and_handoff_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            state = start_phase(
                target,
                "run-001",
                "research",
                {
                    "baseline_status": "complete",
                    "nodes": {
                        "node-001": {
                            "status": "accepted",
                            "critic_ref": "logs/critics/critic-node-001.json",
                            "critic_verdict": "ACCEPT",
                            "critic_evidence_fingerprint": "fp1",
                            "node_evidence_fingerprint": "fp1",
                        }
                    },
                    "selected_node": "node-001",
                    "selection": {"status": "final", "selected_node": "node-001"},
                },
            )
            state["active"] = False
            state["phase_status"] = "complete"
            state["completion_audit"] = {
                "passed": True,
                "prompt_to_artifact_checklist": ["node-001 accepted"],
                "verification_evidence": ["validator passed"],
            }
            state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            state_path.write_text(json.dumps(state, indent=2) + "\n")
            set_active_run(target, "run-001", "research", "active")

            blocked = evaluate_stop_decision(target)
            self.assertEqual(blocked.decision, "block")
            self.assertIn("missing_release_evidence", blocked.reason)

            append_journal_event(target, "run-001", "validation", details={"gate": "research_to_review", "exit_code": 0})
            append_journal_event(target, "run-001", "handoff", details={"gate": "research_to_review", "approved": True, "exit_code": 0})

            allowed = evaluate_stop_decision(target)
            self.assertEqual(allowed.decision, "allow")

    def test_installer_writes_project_hook_and_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            proc = subprocess.run(
                [*CLI_ARGS, "hooks", "install", "--project-root", str(target), "--python", sys.executable],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            hooks = json.loads((target / ".codex" / "hooks.json").read_text())
            self.assertIn("Stop", hooks["hooks"])
            self.assertIn("ai-scientist hooks stop-gate", json.dumps(hooks))
            self.assertIn("hooks = true", (target / ".codex" / "config.toml").read_text())

            check = subprocess.run(
                [*CLI_ARGS, "hooks", "check", "--project-root", str(target), "--python", sys.executable],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(check.returncode, 0, check.stderr)


if __name__ == "__main__":
    unittest.main()

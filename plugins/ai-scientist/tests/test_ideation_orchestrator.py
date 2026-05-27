from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PLUGIN_ROOT / "scripts"
SCRIPT = PLUGIN_ROOT / "scripts" / "ideation_orchestrator.py"
CLI = PLUGIN_ROOT / "scripts" / "ai_scientist_state_cli.py"
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate_run.py"
sys.path.insert(0, str(SCRIPT_DIR))

from ai_scientist_state import evaluate_stop_decision  # noqa: E402


def run_cli(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--target-repo", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def run_validator(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(target), "--gate", "ideation_to_research", "--run-id", "run-001"],
        text=True,
        capture_output=True,
        check=False,
    )


def idea_payload(idea_id: str, title: str = "Fixture idea") -> dict[str, object]:
    return {
        "id": idea_id,
        "title": title,
        "hypothesis": "Changing the model update rule will improve the benchmark score.",
        "expected_metric": "score",
        "risks": ["May not improve over baseline"],
        "novelty_rationale": "The combination has not been tested in this repository.",
    }


def critic_payload(verdict: str = "ACCEPT", score: int = 82) -> dict[str, object]:
    return {
        "verdict": verdict,
        "score": score,
        "strengths": ["Feasible"],
        "weaknesses": ["Needs careful ablation"],
        "required_revisions": [],
        "mode_specific_assessment": {"performance_likelihood": "reasonable"},
        "risk_flags": [],
    }


class AgentDrivenIdeationTests(unittest.TestCase):
    def test_start_and_resume_compute_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            started = run_cli(
                target,
                "ideation",
                "start",
                "--run-id",
                "run-001",
                "--prompt",
                "fixture prompt",
                "--num-ideas",
                "2",
                "--reflection-budget",
                "5",
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertEqual(json.loads(started.stdout)["next_action"], "start_next_idea")

            resumed = run_cli(target, "ideation", "resume", "--run-id", "run-001", "--prompt")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            payload = json.loads(resumed.stdout)
            self.assertEqual(payload["next_action"], "start_next_idea")
            self.assertIn("main Codex ideation orchestrator", payload["prompt"])
            self.assertTrue((target / ".ai-scientist" / "active-run.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "config.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").exists())

    def test_pending_intent_blocks_stop_hook_with_record_result_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            intent = run_cli(target, "ideation", "intent", "start", "--run-id", "run-001", "--role", "generator")
            self.assertEqual(intent.returncode, 0, intent.stderr)

            decision = evaluate_stop_decision(target)

            self.assertEqual(decision.decision, "block")
            self.assertIn("record_subagent_result", decision.system_message)

    def test_stale_critic_hash_blocks_finalization_after_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            first = run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001", "First draft")))
            self.assertEqual(first.returncode, 0, first.stderr)
            critic = run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload()))
            self.assertEqual(critic.returncode, 0, critic.stderr)
            revised = run_cli(target, "idea", "revise-start", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "tighten idea")
            self.assertEqual(revised.returncode, 0, revised.stderr)
            second = run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(idea_payload("idea-001", "Second draft")))
            self.assertEqual(second.returncode, 0, second.stderr)

            finalized = run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001")

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("critic_stale_for_current_idea", finalized.stdout)

    def test_successful_engineer_ideation_validates_and_stop_hook_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            steps = [
                run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1"),
                run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))),
                run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 86))),
                run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001"),
                run_cli(
                    target,
                    "ideation",
                    "rank-finalize",
                    "--run-id",
                    "run-001",
                    "--json",
                    json.dumps(
                        {
                            "selected_idea_id": "idea-001",
                            "ranked_ideas": [
                                {
                                    "idea_id": "idea-001",
                                    "score": 88,
                                    "score_components": {"performance": 45, "feasibility": 25, "repo_fit": 18},
                                    "rationale": "Best expected performance.",
                                }
                            ],
                        }
                    ),
                ),
                run_cli(target, "ideation", "complete", "--run-id", "run-001"),
            ]
            for step in steps:
                self.assertEqual(step.returncode, 0, step.stderr + step.stdout)

            ideas = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").read_text())["ideas"]
            self.assertEqual(ideas[0]["evaluation"], "ACCEPTED")
            self.assertEqual(ideas[0]["rank"], 1)
            validator = run_validator(target)
            self.assertEqual(validator.returncode, 0, validator.stderr)
            self.assertEqual(evaluate_stop_decision(target).decision, "allow")

    def test_ranking_required_when_candidate_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001").returncode, 0)

            completed = run_cli(target, "ideation", "complete", "--run-id", "run-001")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ranking must be finalized", completed.stdout)

    def test_exhausted_no_candidate_is_terminal_but_fails_handoff_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("REJECT", 20))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "reject", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "critic rejected").returncode, 0)
            exhausted = run_cli(target, "ideation", "exhaust", "--run-id", "run-001")
            self.assertEqual(exhausted.returncode, 0, exhausted.stderr + exhausted.stdout)

            self.assertEqual(evaluate_stop_decision(target).decision, "allow")
            validator = run_validator(target)
            self.assertNotEqual(validator.returncode, 0)
            self.assertIn("researchable candidate", validator.stderr)

    def test_old_python_orchestrator_path_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--target-repo", str(target), "--prompt", "fixture"],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("retired", proc.stderr)
            self.assertFalse((SCRIPT_DIR / "ideation_orchestrator_impl.py").exists())
            self.assertNotIn("codex exec", SCRIPT.read_text())


if __name__ == "__main__":
    unittest.main()

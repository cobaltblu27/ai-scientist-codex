from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_ARGS = ["uv", "run", "--project", str(REPO_ROOT), "ai-scientist"]


def research_contract() -> dict[str, object]:
    return {
        "primary_hypothesis": "The intervention improves held-out score on the declared benchmark.",
        "goal_type": "performance",
        "success_criteria": "Held-out score improves over the reference baseline by at least 0.03.",
        "failure_criteria": "A complete experiment fails to improve held-out score under the declared benchmark.",
        "allowed_rescue_scope": "Only explicitly disclosed benchmark hygiene rescues are allowed.",
        "kill_criteria": "Stop when evidence cannot be produced without changing split, benchmark, or environment.",
        "non_drift_definition": "Changing dataset, split, baseline, metric, or evaluator is drift.",
        "metrics_that_matter": ["score"],
        "non_negotiable_comparisons": ["baseline", "declared split"],
        "fixed_dataset": {"name": "Fixture dataset", "path": "data/fixture"},
        "fixed_split": {"name": "Fixture split", "seed": 1},
        "fixed_baseline": {"name": "Reference Benchmark Model"},
        "evaluator_command": "uv run python -m pytest",
        "baseline_reference": {"title": "Reference Benchmark Model", "usability": "Defines the comparable held-out score."},
        "benchmark_plan": "Run baseline and candidate on the same split.",
        "target_threshold": "Candidate score must beat baseline by at least 0.03.",
    }


def final_idea(idea_id: str = "idea-001", family_key: str = "fixture-family") -> dict[str, object]:
    return {
        "id": idea_id,
        "family_key": family_key,
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


def run_cli(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command_args = list(args)
    if len(command_args) >= 2 and command_args[0] == "ideation" and command_args[1] == "start" and "--json" not in command_args and "--json-file" not in command_args:
        command_args.extend(["--json", json.dumps({"research_contract": research_contract()})])
    return subprocess.run([*CLI_ARGS, "--target-repo", str(target), *command_args], text=True, capture_output=True, check=False)


class AgentDrivenIdeationTests(unittest.TestCase):
    def test_start_resume_and_help_are_goal_driven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            target.joinpath("pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            started = run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            self.assertNotIn("next_action", json.loads(started.stdout))

            resumed = run_cli(target, "ideation", "resume", "--run-id", "run-001", "--prompt")
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            self.assertIn("create_goal owns continuation", json.loads(resumed.stdout)["prompt"])

            old_flag = run_cli(target, "ideation", "start", "--run-id", "run-old", "--prompt", "fixture", "--reflection-budget", "1")
            self.assertNotEqual(old_flag.returncode, 0)

    def test_intent_roles_accept_natural_language_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            target.joinpath("pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture").returncode, 0)
            batch = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "selector", "--count", "1")
            self.assertEqual(batch.returncode, 0, batch.stderr + batch.stdout)
            intent = json.loads(batch.stdout)["intents"][0]
            Path(intent["result_path"]).write_text("Select idea-001; it is the most feasible.")

            completed = run_cli(target, "ideation", "intent", "complete", "--run-id", "run-001", "--intent-id", intent["intent_id"])
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(len(state["state"]["artifacts"]["selector_reports"]), 1)

    def test_finalize_complete_and_validate_final_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            target.joinpath("pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture").returncode, 0)
            finalized = run_cli(target, "ideation", "finalize-ready", "--run-id", "run-001", "--json", json.dumps({"ideas": [final_idea()]}))
            self.assertEqual(finalized.returncode, 0, finalized.stderr + finalized.stdout)
            completed = run_cli(target, "ideation", "complete", "--run-id", "run-001")
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)

            validated = subprocess.run([*CLI_ARGS, "validate", "run", str(target), "--gate", "ideation_to_research", "--run-id", "run-001"], text=True, capture_output=True, check=False)
            self.assertEqual(validated.returncode, 0, validated.stderr + validated.stdout)

    def test_finalize_ready_blocks_duplicate_final_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            target.joinpath("pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture").returncode, 0)
            payload = {"ideas": [final_idea("idea-001", "same"), final_idea("idea-002", "same")]}
            finalized = run_cli(target, "ideation", "finalize-ready", "--run-id", "run-001", "--json", json.dumps(payload))
            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("duplicate_idea_family", finalized.stdout)

    def test_top_level_idea_commands_are_trimmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = run_cli(target, "idea", "reject", "--run-id", "run-001", "--reason", "old")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()

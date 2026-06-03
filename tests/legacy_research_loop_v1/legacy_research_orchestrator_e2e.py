from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_support import VALIDATE_RUN_ARGS, make_idea_json, make_research_target, orchestrator_args, read_json, run_python


class ResearchOrchestratorE2ETests(unittest.TestCase):
    def test_fixture_orchestrator_e2e_passes_final_validation_for_maximize_and_minimize(self) -> None:
        cases = [("accuracy", "maximize", 0.60), ("loss", "minimize", 0.60)]
        for metric_key, direction, threshold in cases:
            with self.subTest(direction=direction), TemporaryDirectory() as td:
                tmp = Path(td)
                target = make_research_target(tmp)
                idea = make_idea_json(tmp)
                run_id = f"fixture-{direction}"
                result = run_python(orchestrator_args(target, idea, run_id=run_id, metric_key=metric_key, metric_direction=direction, success_threshold=threshold))
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

                run = target / ".ai-scientist" / "runs" / run_id
                self.assertTrue((run / "baseline" / "metrics.json").exists())
                self.assertTrue((run / "selection.json").exists())
                selection = read_json(run / "selection.json")
                self.assertEqual(selection["metric_key"], metric_key)
                self.assertEqual(selection["metric_direction"], direction)
                self.assertTrue((run / "verifier-decisions" / "research_to_review.json").exists())

                validation = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "research_to_review", "--run-id", run_id, "--validation-mode", "final"])
                self.assertEqual(validation.returncode, 0, validation.stderr + validation.stdout)

    def test_fresh_target_idea_json_bootstrap_creates_governance_non_destructively(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            source = make_research_target(tmp / "source")
            idea = make_idea_json(tmp)
            fresh = tmp / "fresh-target"
            shutil.copytree(source, fresh)
            shutil.rmtree(fresh / ".ai-scientist", ignore_errors=True)

            result = run_python(orchestrator_args(fresh, idea, run_id="fresh-bootstrap", metric_key="accuracy", metric_direction="maximize", success_threshold=0.60))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            ai = fresh / ".ai-scientist"
            run = ai / "runs" / "fresh-bootstrap"
            self.assertTrue((ai / "ideas" / "ideas.json").exists())
            for artifact in [
                ai / "config.json",
                run / "research-plan.json",
                run / "dependency-plan.json",
                run / "dependency-status.json",
                run / "api-ledger.jsonl",
                run / "principles.json",
                run / "run-status.json",
                run / "handoff.jsonl",
                run / "verifier-decisions" / "research_to_review.json",
            ]:
                self.assertTrue(artifact.exists(), f"missing governance artifact: {artifact}")

            keep = ai / "KEEP.txt"
            keep.write_text("preserve me\n")
            second = run_python(orchestrator_args(fresh, idea, run_id="second-run", metric_key="accuracy", metric_direction="maximize", success_threshold=0.60))
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            self.assertEqual(keep.read_text(), "preserve me\n")

    def test_fixture_orchestrator_all_strictness_modes_pass_final_validation(self) -> None:
        for mode in ["scientist", "researcher", "balanced", "builder", "engineer"]:
            with self.subTest(mode=mode), TemporaryDirectory() as td:
                tmp = Path(td)
                target = make_research_target(tmp)
                idea = make_idea_json(tmp)
                run_id = f"fixture-{mode}"
                result = run_python(
                    orchestrator_args(
                        target,
                        idea,
                        run_id=run_id,
                        metric_key="accuracy",
                        metric_direction="maximize",
                        success_threshold=0.60,
                        strictness_mode=mode,
                    )
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                validation = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "research_to_review", "--run-id", run_id, "--validation-mode", "final"])
                self.assertEqual(validation.returncode, 0, validation.stderr + validation.stdout)


if __name__ == "__main__":
    unittest.main()

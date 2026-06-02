from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_support import VALIDATE_RUN_ARGS, run_python, write_minimal_research_run, write_json


class ValidateRunResearchGateTests(unittest.TestCase):
    def test_final_validation_fails_without_approved_gate_specific_verifier_decision(self) -> None:
        for decision in [None, "blocked", "rejected"]:
            with self.subTest(decision=decision), TemporaryDirectory() as td:
                target = Path(td) / "target"
                target.mkdir()
                write_minimal_research_run(target, decision=decision)

                result = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "research_to_review", "--run-id", "run-001", "--validation-mode", "final"])

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("verifier", (result.stderr + result.stdout).lower())

    def test_final_validation_rejects_launch_verifier_decision_as_research_gate_substitute(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            run = write_minimal_research_run(target, decision=None)
            write_json(run / "verifier-decision.json", {"decision": "go", "blockers": []})

            result = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "research_to_review", "--run-id", "run-001", "--validation-mode", "final"])

            self.assertNotEqual(result.returncode, 0)
            output = result.stderr + result.stdout
            self.assertTrue("research_to_review" in output or "verifier" in output.lower())

    def test_final_validation_rejects_stale_evidence_after_approved_decision(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            run = write_minimal_research_run(target, decision="approved")
            summary = run / "nodes" / "node-001" / "result_summary.json"
            write_json(summary, {"summary": "candidate improved after validation snapshot changed"})

            result = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "research_to_review", "--run-id", "run-001", "--validation-mode", "final"])

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stale", (result.stderr + result.stdout).lower())


if __name__ == "__main__":
    unittest.main()

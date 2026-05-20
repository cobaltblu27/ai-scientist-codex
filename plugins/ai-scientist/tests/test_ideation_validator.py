from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_support import PLUGIN_ROOT, read_json, read_jsonl, write_json

import finalize_ideation
import ideation_state
import semantic_scholar_search
import validate_idea


def proposal_grade_idea() -> dict:
    return {
        "id": "idea-001",
        "title": "Benchmark-Preserving Leakage-Aware Intervention",
        "hypothesis": "A benchmark-preserving intervention will improve held-out accuracy while reducing leakage-driven error compared with the named baseline.",
        "scientific_insight": "The proposal isolates whether the measured improvement comes from a mechanism that changes generalization behavior rather than from hidden split drift, extra data access, or broader capacity. It predicts a measurable accuracy improvement only when the mechanism is present and the benchmark policy is fixed.",
        "related_work": "Benchmark-Preserving Experiment Design motivates fixed split comparisons, while Leakage-Aware Model Evaluation shows why leakage checks must accompany held-out metrics. This proposal differs by requiring both papers' controls in the ideation acceptance criteria.",
        "abstract": "This proposal tests a small benchmark-preserving intervention under fixed data access and evaluation rules. It compares the existing baseline, the proposed method, and a matched ablation on held-out accuracy while logging split integrity and leakage evidence. The expected result is not only a metric gain but a pattern of failures that supports or weakens the hypothesized mechanism. The work is intentionally narrow so a later research-loop agent can implement and audit it without inventing new scientific assumptions.",
        "novelty_rationale": "The novelty is the paired mechanism and leakage-aware evaluation contract, not a generic attempt to tune the benchmark.",
        "required_data": "The target benchmark dataset, fixed train/validation/test split manifest, baseline command logs, and cached Semantic Scholar search summaries.",
        "expected_metric": "Held-out accuracy on the declared benchmark split, compared against baseline and matched ablation.",
        "execution_plan": [
            {
                "step": "Reproduce baseline",
                "purpose": "Establish the fixed comparison before changing the method.",
                "dataset": "Declared benchmark dataset and fixed split manifest.",
                "model": "Existing repository baseline model.",
                "evaluation": "Held-out accuracy with leakage and split-integrity checks.",
                "method": "Run the baseline command and record metrics, command logs, split integrity, leakage evidence, and resource usage.",
                "success_criteria": "Baseline artifacts include the expected metric and validation evidence.",
            },
            {
                "step": "Implement intervention",
                "purpose": "Test the proposed mechanism with one small code or config change.",
                "dataset": "Same declared benchmark dataset and split.",
                "model": "Baseline model plus the targeted intervention.",
                "evaluation": "Held-out accuracy using the same evaluator as baseline.",
                "method": "Apply only the proposed mechanism and run the same evaluation protocol with matched data access.",
                "success_criteria": "The intervention completes and writes comparable metrics.",
            },
            {
                "step": "Run matched ablation",
                "purpose": "Separate the mechanism from generic capacity or tuning effects.",
                "dataset": "Same declared benchmark dataset and split.",
                "model": "Intervention model with the mechanism disabled.",
                "evaluation": "Held-out accuracy and comparison against intervention and baseline.",
                "method": "Disable the mechanism while preserving training budget, then rerun evaluation.",
                "success_criteria": "The mechanism-bearing variant beats the ablation.",
            },
            {
                "step": "Analyze failures",
                "purpose": "Convert metric movement into interpretable scientific evidence.",
                "dataset": "Held-out examples grouped by relevant benchmark regimes.",
                "model": "Baseline, intervention, and ablation outputs.",
                "evaluation": "Failure slices tied to the same held-out metric.",
                "method": "Break down representative errors and compare the pattern against the hypothesis.",
                "success_criteria": "The report states where the mechanism helps, where it fails, and why.",
            },
        ],
        "experiments": [
            "Run the baseline on the fixed split and evaluate held-out accuracy with split and leakage artifacts.",
            "Run the proposed intervention and compare held-out accuracy against the baseline under matched data access.",
            "Run a matched ablation that disables the mechanism and compare against the intervention.",
        ],
        "risks": [
            "The intervention may fail because the apparent effect is a spurious split artifact.",
            "The result may overfit the benchmark or expose leakage that invalidates the metric gain.",
        ],
        "minimum_evidence": [
            "A baseline command log and held-out metric artifact must exist.",
            "The intervention must pass the same evaluation command and threshold comparison.",
            "The matched ablation must be compared against the intervention.",
            "Split integrity and leakage validation artifacts must pass.",
        ],
        "semantic_scholar_queries": ["benchmark preserving experiment leakage evaluation"],
    }


class IdeationValidatorTests(unittest.TestCase):
    def test_validate_accepts_proposal_with_cached_citations(self) -> None:
        with TemporaryDirectory() as td:
            cache = Path(td) / "search.json"
            write_json(
                cache,
                {
                    "results": [
                        {"title": "Benchmark-Preserving Experiment Design"},
                        {"title": "Leakage-Aware Model Evaluation"},
                    ]
                },
            )
            self.assertEqual(validate_idea.validate_idea(proposal_grade_idea(), [cache]), [])

    def test_validate_rejects_pretty_but_weak_idea(self) -> None:
        idea = proposal_grade_idea()
        idea["related_work"] = "Some related work exists but is not cited concretely."
        idea["hypothesis"] = "This might be better."
        errors = validate_idea.validate_idea(idea, [])
        self.assertIn("hypothesis must name a measurable dependent variable or metric", errors)
        self.assertIn("related_work must cite at least 2 papers from the Semantic Scholar search cache", errors)

    def test_semantic_scholar_fixture_writes_cache_and_ledger(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(target, "study ideas", run_id="ideation-test")
            results, cache_path = semantic_scholar_search.search_and_record(
                target,
                state["run_id"],
                "fixture query",
                state["current_idea_id"],
                1,
                fixture_path=PLUGIN_ROOT / "tests" / "fixtures" / "semantic-scholar" / "minimal-results.json",
            )

            self.assertEqual(len(results), 2)
            self.assertTrue(cache_path.exists())
            self.assertTrue((target / ".ai-scientist" / "logs" / "ideation-test" / "semantic-scholar-cache" / cache_path.name).exists())
            ledger = read_jsonl(target / ".ai-scientist" / "runs" / "ideation-test" / "api-ledger.jsonl")
            self.assertEqual(ledger[0]["provider"], "semantic_scholar")
            self.assertFalse(ledger[0]["cached"])

    def test_finalize_ideation_writes_valid_gate_artifacts(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            (target / "README.md").write_text("fixture target\n")
            state = ideation_state.initialize_ideation(target, "study ideas", run_id="ideation-test", target_num_ideas=1)
            _, cache_path = semantic_scholar_search.search_and_record(
                target,
                state["run_id"],
                "fixture query",
                state["current_idea_id"],
                1,
                fixture_path=PLUGIN_ROOT / "tests" / "fixtures" / "semantic-scholar" / "minimal-results.json",
            )
            state = ideation_state.advance_after_search(target, state, cache_path)
            state = ideation_state.add_finalized_idea(target, state, proposal_grade_idea())
            result = finalize_ideation.finalize_ideation(target, state, PLUGIN_ROOT)

            self.assertTrue(result["ok"], result)
            self.assertEqual(read_json(target / ".ai-scientist" / "runs" / "ideation-test" / "run-status.json")["status"], "validated")
            self.assertEqual(len(read_json(target / ".ai-scientist" / "ideas" / "ideas.json")["ideas"]), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
from test_support import PLUGIN_ROOT

ideation = importlib.import_module("ideation_orchestrator")


class IdeationPromptSchemaTests(unittest.TestCase):
    def test_schema_requires_proposal_grade_scientific_fields(self) -> None:
        required = set(ideation.IDEA_OUTPUT_SCHEMA["required"])
        for field in {
            "scientific_insight",
            "related_work",
            "abstract",
            "novelty_rationale",
            "execution_plan",
            "experiments",
            "minimum_evidence",
        }:
            self.assertIn(field, required)
        execution_plan = ideation.IDEA_OUTPUT_SCHEMA["properties"]["execution_plan"]
        self.assertGreaterEqual(execution_plan["minItems"], 4)
        self.assertEqual(
            set(execution_plan["items"]["required"]),
            {"step", "purpose", "method", "success_criteria"},
        )

    def test_persisted_idea_schema_matches_required_related_work_contract(self) -> None:
        schema = json.loads((PLUGIN_ROOT / "schemas" / "idea.schema.json").read_text())
        item_schema = schema["properties"]["ideas"]["items"]
        self.assertIn("related_work", item_schema["required"])
        self.assertIn("scientific_insight", item_schema["required"])
        self.assertIn("execution_plan", item_schema["required"])

    def test_prompts_reject_thin_metric_tickets(self) -> None:
        proposal = ideation.build_proposal_prompt("study drug-blind IC50 prediction", "idea-001", "scientist", [])
        reflection = ideation.build_reflection_prompt(
            "study drug-blind IC50 prediction",
            "idea-001",
            "scientist",
            {"id": "idea-001", "title": "Thin idea"},
            [],
            1,
            5,
            [],
        )
        finalization = ideation.build_finalization_prompt(
            "study drug-blind IC50 prediction",
            "idea-001",
            "scientist",
            {"id": "idea-001", "title": "Thin idea"},
            [],
            1,
            5,
        )
        combined = "\n".join([proposal, reflection, finalization]).lower()
        for phrase in [
            "scientific insight",
            "related work",
            "execution plan",
            "baseline",
            "ablations",
            "leakage",
            "thin metric-improvement ticket",
        ]:
            self.assertIn(phrase, combined)

    def test_ideation_defaults_to_deep_codex_agent_settings(self) -> None:
        self.assertEqual(ideation.DEFAULT_CODEX_IDEATION_MODEL, "gpt-5.5")
        self.assertEqual(ideation.DEFAULT_CODEX_IDEATION_REASONING_EFFORT, "xhigh")


if __name__ == "__main__":
    unittest.main()

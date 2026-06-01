from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
from test_support import PLUGIN_ROOT

from ideation.state import DEFAULT_IDEATION_CONFIG, IDEA_OUTPUT_SCHEMA


class IdeationPromptSchemaTests(unittest.TestCase):
    def test_schema_requires_compact_vnext_fields(self) -> None:
        required = set(IDEA_OUTPUT_SCHEMA["required"])
        for field in {
            "family_key",
            "unique_protocol",
            "expected_metric",
            "smoke_runnable_now",
            "requires_implementation",
            "minimum_command",
            "evidence_refs",
            "rubric_scores",
            "risk_flags",
        }:
            self.assertIn(field, required)

    def test_persisted_idea_schema_matches_compact_contract(self) -> None:
        schema = json.loads((PLUGIN_ROOT / "schemas" / "idea.schema.json").read_text())
        item_schema = schema["properties"]["ideas"]["items"]
        for field in IDEA_OUTPUT_SCHEMA["required"]:
            self.assertIn(field, item_schema["required"])

    def test_prompts_request_json_only_compact_payloads(self) -> None:
        modes = DEFAULT_IDEATION_CONFIG["modes"]
        combined = "\n".join(
            [
                modes["scientist"]["idea_generation_prompt_template"],
                modes["scientist"]["critic_prompt_template"],
                modes["scientist"]["ranking_prompt_template"],
            ]
        ).lower()
        for phrase in [
            "json",
            "research idea",
            "critic",
            "rank",
            "verdict",
        ]:
            self.assertIn(phrase, combined)

    def test_ideation_defaults_to_six_subagents(self) -> None:
        self.assertEqual(DEFAULT_IDEATION_CONFIG["concurrency"]["max_subagents"], 6)


if __name__ == "__main__":
    unittest.main()

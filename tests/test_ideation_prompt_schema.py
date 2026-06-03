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

    def test_ideation_mode_prompt_files_exist(self) -> None:
        modes = DEFAULT_IDEATION_CONFIG["modes"]
        self.assertEqual(set(modes), {"scientist", "engineer", "custom"})
        for mode, preset in modes.items():
            for key, role in {
                "generator_prompt": "generator",
                "critic_prompt": "critic",
                "ranker_prompt": "ranker",
            }.items():
                prompt_path = preset[key]
                self.assertEqual(prompt_path, f"prompts/ideation/{mode}/{role}.md")
                prompt_text = (PLUGIN_ROOT / prompt_path).read_text().lower()
                self.assertIn("json", prompt_text)
                self.assertIn(role, prompt_text)

    def test_shipped_config_uses_prompt_paths_not_inline_templates(self) -> None:
        config = json.loads((PLUGIN_ROOT / "config" / "config.json").read_text())
        modes = config["ideation"]["modes"]
        self.assertEqual(set(modes), {"scientist", "engineer", "custom"})
        for preset in modes.values():
            self.assertIn("generator_prompt", preset)
            self.assertIn("critic_prompt", preset)
            self.assertIn("ranker_prompt", preset)
            self.assertNotIn("idea_generation_prompt_template", preset)
            self.assertNotIn("critic_prompt_template", preset)
            self.assertNotIn("ranking_prompt_template", preset)

    def test_literature_search_skill_is_referenced_by_ideation(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "literature-search" / "SKILL.md").read_text()
        ideation = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        self.assertIn("OpenAlex first", skill)
        self.assertIn("Semantic Scholar", skill)
        self.assertIn("Generator subagents should use this skill directly", skill)
        self.assertIn("Subagents may run the `ai-scientist` CLI literature command", skill)
        self.assertIn("Preflight references found before generator subagents exist are advisory only", skill)
        self.assertIn("skills/literature-search/SKILL.md", ideation)

    def test_ideation_pre_generation_synthesis_order_is_prompt_only(self) -> None:
        ideation = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        ordered_terms = [
            "Preflight reference scan.",
            "Heiemeier question pass.",
            "Generator assignment synthesis.",
            "Generator intent batch.",
        ]
        positions = [ideation.index(term) for term in ordered_terms]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("skills/heiemeier-question/SKILL.md", ideation)
        self.assertIn("This sequence is orchestration guidance, not a new CLI lifecycle gate", ideation)
        self.assertIn("Do not create new required artifacts, new cursor actions, or new Stop-hook blockers", ideation)

    def test_generator_prompts_require_literature_search_skill(self) -> None:
        for mode in ["scientist", "engineer", "custom"]:
            prompt = (PLUGIN_ROOT / "prompts" / "ideation" / mode / "generator.md").read_text()
            self.assertIn("skills/literature-search/SKILL.md", prompt)
            self.assertIn("assigned idea id", prompt)
            self.assertIn("raw `curl`", prompt)
            self.assertIn("preflight reference papers", prompt)
            self.assertIn("Heiemeier answers/insights", prompt)
            self.assertIn("not a substitute for canonical evidence", prompt)

    def test_heiemeier_question_skill_invocation_boundary(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "heiemeier-question" / "SKILL.md").read_text()
        self.assertIn("name: heiemeier-question", skill)
        self.assertIn("lay out the questions", skill.lower())
        self.assertIn("answer each question in order", skill.lower())
        self.assertIn("What are you trying to do?", skill)
        self.assertIn("What are the midterm and final exams", skill)
        self.assertIn("another explicitly active skill names this skill as a required step", skill)

    def test_ideation_defaults_to_six_subagents(self) -> None:
        self.assertEqual(DEFAULT_IDEATION_CONFIG["concurrency"]["max_subagents"], 6)


if __name__ == "__main__":
    unittest.main()

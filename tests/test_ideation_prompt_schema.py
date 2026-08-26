from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
from test_support import PLUGIN_ROOT


class IdeationPromptSchemaTests(unittest.TestCase):
    def test_create_contract_skill_is_explicit_and_state_free(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "create-contract" / "SKILL.md").read_text()
        self.assertIn("name: create-contract", skill)
        self.assertIn("Explicit-only", skill)
        self.assertIn("Use this skill ONLY when the user explicitly asks", skill)
        self.assertIn(".ai-scientist/contracts/<contract-id>/research-contract.json", skill)
        self.assertIn("does not start ideation", skill)
        self.assertIn("does not start research-loop", skill)
        self.assertIn("does not create loop state", skill)
        self.assertIn("does not spawn agents", skill)
        self.assertIn("Do not call `ideation start`", skill)
        self.assertIn("Do not invent dataset, split protocol, allowed or forbidden inputs", skill)

    def test_create_contract_template_matches_reference_top_level_schema(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "create-contract" / "SKILL.md").read_text()
        template_text = skill.split("```json", 1)[1].split("```", 1)[0]
        template = json.loads(template_text)
        self.assertEqual(list(template), ["research_contract"])
        contract = template["research_contract"]
        self.assertEqual(
            list(contract),
            [
                "goal_type",
                "primary_hypothesis",
                "dataset",
                "split_protocol",
                "allowed_inputs",
                "forbidden_inputs",
                "metrics",
                "metrics_that_matter",
                "non_negotiable_comparisons",
                "baseline_reference",
                "benchmark_plan",
                "evaluator_command",
                "success_criteria",
                "failure_criteria",
                "kill_criteria",
                "target_threshold",
                "non_drift_definition",
            ],
        )
        self.assertNotIn("allowed_rescue_scope", contract)
        self.assertEqual(contract["metrics"], {"primary": "", "secondary": []})
        self.assertIsInstance(contract["dataset"], dict)
        for field in [
            "allowed_inputs",
            "forbidden_inputs",
            "metrics_that_matter",
            "non_negotiable_comparisons",
            "kill_criteria",
        ]:
            self.assertIsInstance(contract[field], list)

    def test_ideation_skill_is_goal_and_artifact_driven(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        self.assertIn("create_goal", skill)
        self.assertIn("ai-scientist agents check", skill)
        self.assertIn("contract.json", skill)
        self.assertIn("ideas/<idea-id>.md", skill)
        self.assertIn("logs/pilots/<idea-id>/report.md", skill)
        self.assertIn("lightweight `ideas.json` index", skill)
        self.assertIn("status: complete", skill)
        self.assertNotIn("ai-scientist ideation start", skill)
        self.assertNotIn("ideation finalize-ready", skill)

    def test_ideation_generated_agent_prompts_exist(self) -> None:
        for mode in {"scientist", "engineer", "custom"}:
            generator = (PLUGIN_ROOT / "prompts" / "ideation" / mode / "generator.md").read_text()
            critic = (PLUGIN_ROOT / "prompts" / "ideation" / mode / "critic.md").read_text()
            self.assertIn("contract", generator.lower())
            self.assertIn("contract", critic.lower())
        scientist_critic = (PLUGIN_ROOT / "prompts" / "ideation" / "scientist" / "critic.md").read_text()
        self.assertIn("constructive feedback provider, not an acceptance gate", scientist_critic)
        self.assertIn("Do not accept", scientist_critic)

if __name__ == "__main__":
    unittest.main()

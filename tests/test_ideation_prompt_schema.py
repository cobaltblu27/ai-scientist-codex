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
        self.assertIn("disable-model-invocation: true", skill)
        self.assertIn("Explicit-only", skill)
        self.assertIn(".ai-scientist/contracts/<contract-id>/research-contract.json", skill)
        self.assertIn("does not start ideation", skill)
        self.assertIn("does not start research-loop", skill)
        self.assertIn("does not create loop state", skill)
        self.assertIn("does not spawn agents", skill)
        self.assertIn("Do not invent dataset, split protocol, allowed or forbidden inputs", skill)

    def test_create_contract_template_matches_reference_top_level_schema(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "create-contract" / "SKILL.md").read_text()
        template_text = skill.split("```json", 1)[1].split("```", 1)[0]
        template = json.loads(template_text)
        self.assertEqual(list(template), ["research_contract"])
        contract = template["research_contract"]
        self.assertIn("goal", contract)
        self.assertIn("non_drift_definition", contract)
        self.assertNotIn("allowed_rescue_scope", contract)
        self.assertEqual(contract["metrics"], {"primary": "", "secondary": []})
        self.assertIsInstance(contract["dataset"], dict)
        for field in [
            "allowed_inputs",
            "forbidden_inputs",
            "related_works",
        ]:
            self.assertIsInstance(contract[field], list)

    def test_ideation_skill_is_claude_agent_and_artifact_driven(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        self.assertIn("disable-model-invocation: true", skill)
        self.assertIn("Claude Code's Agent tool", skill)
        self.assertIn("ai-scientist:ai-scientist-ideation-generator", skill)
        self.assertIn("`/goal`", skill)
        self.assertNotIn("create_goal", skill)
        self.assertNotIn("ai-scientist agents check", skill)
        self.assertIn("contract.json", skill)
        self.assertIn("ideas/<idea-id>.md", skill)
        self.assertIn("logs/pilots/<idea-id>/report.md", skill)
        self.assertIn("lightweight `ideas.json` index", skill)
        self.assertIn("status: complete", skill)
        self.assertNotIn("ai-scientist ideation start", skill)
        self.assertNotIn("ideation finalize-ready", skill)

    def test_ideation_agent_prompts_exist(self) -> None:
        generator = (PLUGIN_ROOT / "agents" / "ai-scientist-ideation-generator.toml").read_text()
        critic = (PLUGIN_ROOT / "agents" / "ai-scientist-ideation-critic.toml").read_text()
        self.assertIn("contract", generator.lower())
        self.assertIn("contract", critic.lower())
        self.assertIn("constructive feedback provider, not an acceptance gate", critic)
        self.assertIn("Do not accept", critic)

if __name__ == "__main__":
    unittest.main()

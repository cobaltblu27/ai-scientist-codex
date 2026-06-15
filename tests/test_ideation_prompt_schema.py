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
    def test_create_contract_skill_contract_and_boundaries(self) -> None:
        skill_path = PLUGIN_ROOT / "skills" / "create-contract" / "SKILL.md"
        self.assertTrue(skill_path.exists())
        skill = skill_path.read_text()
        self.assertIn("name: create-contract", skill)
        self.assertIn("Explicit-only", skill)
        self.assertIn("Use this skill ONLY when the user explicitly asks", skill)
        self.assertIn(".ai-scientist/contracts/<contract-id>/research-contract.json", skill)
        self.assertIn("does not start ideation", skill)
        self.assertIn("does not start research-loop", skill)
        self.assertIn("does not create loop state", skill)
        self.assertIn("does not spawn agents", skill)
        for forbidden_command in [
            "`ideation start`",
            "`research start`",
            "`resume`",
            "`checkpoint`",
        ]:
            self.assertIn(forbidden_command, skill)
        for forbidden_artifact in [
            ".ai-scientist/active-run.json",
            ".ai-scientist/runs/<run-id>/config.json",
            ".ai-scientist/runs/<run-id>/loop-state.json",
            ".ai-scientist/runs/<run-id>/journal.jsonl",
        ]:
            self.assertIn(forbidden_artifact, skill)
        for field in [
            "primary_hypothesis",
            "goal_type",
            "success_criteria",
            "failure_criteria",
            "allowed_rescue_scope",
            "kill_criteria",
            "non_drift_definition",
            "metrics_that_matter",
            "non_negotiable_comparisons",
            "fixed_dataset",
            "fixed_split",
            "fixed_baseline",
            "evaluator_command",
            "baseline_reference",
            "benchmark_plan",
            "target_threshold",
        ]:
            self.assertIn(f'"{field}"', skill)
        for contaminated_field in [
            "prompt",
            "raw_prompt",
            "messages",
            "conversation",
            "transcript",
            "instructions",
            "system_prompt",
            "developer_prompt",
            "assignment_prompt",
            "context_dump",
        ]:
            self.assertIn(f"`{contaminated_field}`", skill)
        self.assertIn("Do not invent dataset, split, baseline, metric, threshold, evaluator command, success criteria, or failure criteria", skill)
        self.assertIn("Keep `failure_criteria` limited to what the user specified", skill)

    def test_ideation_and_research_loop_reference_create_contract(self) -> None:
        ideation = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        research_loop = (PLUGIN_ROOT / "skills" / "research-loop" / "SKILL.md").read_text()
        self.assertIn("skills/create-contract/SKILL.md", ideation)
        self.assertIn("Do not start ideation during contract creation", ideation)
        self.assertIn("skills/create-contract/SKILL.md", research_loop)
        self.assertIn("missing, ambiguous, incomplete, or likely contaminated", research_loop)
        self.assertIn("Do not start the research loop until the contract is clean", research_loop)

    def test_subagent_prompts_have_persona_blocks(self) -> None:
        prompt_paths = sorted((PLUGIN_ROOT / "prompts").rglob("*.md"))
        self.assertTrue(prompt_paths)
        for path in prompt_paths:
            text = path.read_text()
            with self.subTest(path=path.relative_to(PLUGIN_ROOT)):
                self.assertIn("<Persona>", text)
                self.assertIn("<Id>", text)
                self.assertIn("<Ego>", text)
                self.assertIn("<Superego>", text)
                self.assertIn("</Persona>", text)
                self.assertIn("discovery", text.lower())
                self.assertIn("stronger", text.lower())
                if path.name == "revision-worker.md" or path.name == "generator.md":
                    self.assertIn("Curiosity", text)
                elif path.name == "critic.md":
                    self.assertIn("Honesty, helpfulness, and ruthlessness", text)
                elif path.name == "ranker.md":
                    self.assertIn("Disciplined taste", text)
                else:
                    self.assertIn("Thoroughness and meticulousness", text)

    def test_schema_requires_compact_vnext_fields(self) -> None:
        required = set(IDEA_OUTPUT_SCHEMA["required"])
        for field in {
            "family_key",
            "unique_protocol",
            "expected_metric",
            "mechanism",
            "implementation_sketch",
            "expected_metric_effect",
            "fit_to_research_contract",
            "novelty_angle",
            "smoke_runnable_now",
            "requires_implementation",
            "minimum_command",
            "evidence_refs",
            "rubric_scores",
            "risk_flags",
        }:
            self.assertIn(field, required)
        self.assertNotIn("research_contract", required)

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
                "generator_prompt_source": "generator",
                "critic_prompt_source": "critic",
                "ranker_prompt": "ranker",
            }.items():
                prompt_path = preset[key]
                self.assertEqual(prompt_path, f"prompts/ideation/{mode}/{role}.md")
                prompt_text = (PLUGIN_ROOT / prompt_path).read_text().lower()
                self.assertIn("json", prompt_text)
                self.assertIn(role, prompt_text)
            self.assertEqual(preset["generator_agent"], f"ai-scientist-ideation-generator-{mode}")
            self.assertEqual(preset["critic_agent"], f"ai-scientist-ideation-critic-{mode}")

    def test_shipped_config_uses_agents_and_prompt_sources_not_inline_templates(self) -> None:
        config = json.loads((PLUGIN_ROOT / "config" / "config.json").read_text())
        modes = config["ideation"]["modes"]
        self.assertEqual(set(modes), {"scientist", "engineer", "custom"})
        for mode, preset in modes.items():
            self.assertEqual(preset["generator_agent"], f"ai-scientist-ideation-generator-{mode}")
            self.assertEqual(preset["critic_agent"], f"ai-scientist-ideation-critic-{mode}")
            self.assertIn("generator_prompt_source", preset)
            self.assertIn("critic_prompt_source", preset)
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
            self.assertIn("run-owned `research_contract`", prompt)
            self.assertIn("fit_to_research_contract", prompt)
            self.assertIn("Do not create or edit a per-idea `research_contract`", prompt)

    def test_fixed_contract_campaign_prompt_contracts(self) -> None:
        ideation = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        self.assertIn("run-owned `research_contract`", ideation)
        self.assertIn("accepted idea batch", ideation)
        self.assertIn("handoff.idea_batch", ideation)
        self.assertIn("Ranking is legacy/manual only", ideation)
        self.assertNotIn("finalized ranking", ideation)
        self.assertIn("<Persona>", ideation)
        self.assertIn("You are curious and aesthetically demanding", ideation)
        self.assertIn("You are the idea curator", ideation)
        self.assertIn("worth spending research-loop resources on", ideation)

    def test_research_prompts_use_learning_notes_and_campaign_verdicts(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "research-loop" / "SKILL.md").read_text()
        worker = (PLUGIN_ROOT / "prompts" / "research-loop" / "worker.md").read_text()
        self.assertIn("idea_batch", skill)
        self.assertIn("learning-notes.jsonl", skill)
        self.assertIn("resource_queue", skill)
        self.assertIn("borrowed_from_node_id", skill)
        self.assertIn("node seed idea", worker)
        self.assertIn("learning_notes_ref", worker)
        for mode in ["scientist", "engineer", "custom"]:
            critic = (PLUGIN_ROOT / "prompts" / "research-loop" / mode / "critic.md").read_text()
            revision = (PLUGIN_ROOT / "prompts" / "research-loop" / mode / "revision-worker.md").read_text()
            self.assertIn("PROMISING_CONTINUE", critic)
            self.assertIn("NEEDS_SCIENTIFIC_FRAMING", critic)
            self.assertIn("KILL", critic)
            self.assertIn("learning notes", critic.lower())
            self.assertIn("borrowed_from_node_id", revision)
            self.assertIn("insight_ref", revision)

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
        self.assertEqual(DEFAULT_IDEATION_CONFIG["reflection_budget_per_idea"], 10)
        self.assertEqual(DEFAULT_IDEATION_CONFIG["max_attempts_per_slot"], 3)

    def test_ideation_prompts_define_reject_as_fresh_respawn(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "ideation" / "SKILL.md").read_text()
        self.assertIn("`REJECT` means kill the current attempt and respawn a fully fresh generator for the same slot", skill)
        for mode in ["scientist", "engineer", "custom"]:
            critic = (PLUGIN_ROOT / "prompts" / "ideation" / mode / "critic.md").read_text()
            generator = (PLUGIN_ROOT / "prompts" / "ideation" / mode / "generator.md").read_text()
            self.assertIn("respawn a fully fresh generator for the same slot", critic)
            self.assertIn("do not use rejected draft details", generator)
            for verdict in ["ACCEPT", "ACCEPT_WITHOUT_REFERENCE", "REVISE", "REJECT"]:
                self.assertIn(f"## `{verdict}`:", critic)
            self.assertGreaterEqual(critic.count("Examples:"), 4)

    def test_ideation_acceptance_requires_mechanistic_reason_to_work(self) -> None:
        required_terms = [
            "Acceptance_Mechanism_Bar",
            "Acceptance_Probe_Filters",
            "credible mechanism",
            "Information-use probe",
            "Measurement probe",
            "Data-quirk probe",
            "Mechanism probe",
            "Transfer probe",
            "Non-drift probe",
            "overfitting",
            "underfitting",
            "transfer-learning",
            "inductive bias",
            "optimization",
            "calibration",
            "representation",
            "Which dimension should improve",
            "apples-to-apples",
            "leakage risk",
        ]
        for mode in ["scientist", "engineer", "custom"]:
            critic = (PLUGIN_ROOT / "prompts" / "ideation" / mode / "critic.md").read_text()
            for term in required_terms:
                self.assertIn(term, critic)
            self.assertIn("gives a strong", critic)
            self.assertIn("reason it should work", critic)


if __name__ == "__main__":
    unittest.main()

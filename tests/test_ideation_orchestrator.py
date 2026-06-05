from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
CLI_ARGS = ["uv", "run", "--project", str(REPO_ROOT), "ai-scientist"]
VALIDATOR_ARGS = [*CLI_ARGS, "validate", "run"]

from core.state import evaluate_stop_decision


def research_contract(goal_type: str = "performance") -> dict[str, object]:
    contract: dict[str, object] = {
        "primary_hypothesis": "The intervention improves held-out score on the declared benchmark.",
        "goal_type": goal_type,
        "success_criteria": "Held-out score improves over the reference baseline by at least 0.03 in the declared benchmark.",
        "failure_criteria": "A fully implemented and validated experiment fails to improve held-out score under the declared benchmark.",
        "allowed_rescue_scope": "Only explicitly disclosed benchmark hygiene rescue findings are allowed.",
        "kill_criteria": "Stop when evidence cannot be produced without changing split, benchmark, or environment.",
        "non_drift_definition": "A report about dataset properties or an underimplemented negative result is claim drift.",
        "metrics_that_matter": ["score"],
        "non_negotiable_comparisons": ["baseline", "declared split", "reference paper"],
        "fixed_dataset": {"name": "Fixture dataset", "path": "data/fixture"},
        "fixed_split": {"name": "Fixture split", "seed": 1},
        "fixed_baseline": {"name": "Reference Benchmark Model"},
        "evaluator_command": "uv run python -m pytest",
    }
    if goal_type == "performance":
        contract.update(
            {
                "baseline_reference": {
                    "title": "Reference Benchmark Model",
                    "usability": "Use the paper's reported protocol to define the comparable held-out score; if the exact score is absent, rerun the benchmark plan below.",
                },
                "benchmark_plan": "Run the repository baseline and candidate on the same split and calculate held-out score with the declared metric.",
                "target_threshold": "Candidate score must beat baseline by at least 0.03.",
            }
        )
    return contract


def run_cli(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command_args = list(args)
    if len(command_args) >= 2 and command_args[0] == "ideation" and command_args[1] == "start" and "--json" not in command_args and "--json-file" not in command_args:
        command_args.extend(["--json", json.dumps({"research_contract": research_contract()})])
    return subprocess.run(
        [*CLI_ARGS, "--target-repo", str(target), *command_args],
        text=True,
        capture_output=True,
        check=False,
    )


def run_validator(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*VALIDATOR_ARGS, str(target), "--gate", "ideation_to_research", "--run-id", "run-001"],
        text=True,
        capture_output=True,
        check=False,
    )


def idea_payload(idea_id: str, title: str = "Fixture idea") -> dict[str, object]:
    return {
        "id": idea_id,
        "title": title,
        "hypothesis": "Changing the model update rule will improve the benchmark score.",
        "research_contract": research_contract(),
        "expected_metric": "score",
        "risks": ["May not improve over baseline"],
        "novelty_rationale": "The combination has not been tested in this repository.",
        "mechanism": "Changes the update rule to improve representation quality.",
        "implementation_sketch": "Implement the update rule in the existing model path.",
        "expected_metric_effect": "Improve held-out score under the fixed evaluator.",
        "fit_to_research_contract": "Uses the fixed fixture dataset, split, baseline, metric, and evaluator unchanged.",
        "novelty_angle": "A repo-specific combination of update rule and benchmark framing.",
    }


def critic_payload(verdict: str = "ACCEPT", score: int = 82) -> dict[str, object]:
    return {
        "verdict": verdict,
        "score": score,
        "strengths": ["Feasible"],
        "weaknesses": ["Needs careful ablation"],
        "required_revisions": [],
        "mode_specific_assessment": {"performance_likelihood": "reasonable"},
        "risk_flags": [],
    }


def compact_payload(idea_id: str, title: str, family_key: str | None = None, *, score: int = 80) -> dict[str, object]:
    return {
        "id": idea_id,
        "family_key": family_key or idea_id,
        "title": title,
        "hypothesis": "This protocol will improve held-out score over the baseline.",
        "research_contract": research_contract(),
        "unique_protocol": f"Run baseline, apply {title}, compare held-out score.",
        "expected_metric": "score",
        "smoke_runnable_now": True,
        "requires_implementation": [],
        "minimum_command": "uv run python -m pytest",
        "evidence_refs": [],
        "rubric_scores": {"performance": score, "feasibility": score, "repo_fit": score, "novelty": 40},
        "risk_flags": ["May not improve baseline"],
        "mechanism": "Changes the scoring path while keeping the benchmark fixed.",
        "implementation_sketch": f"Apply {title} in the existing model path.",
        "expected_metric_effect": "Improve held-out score over the reference baseline.",
        "fit_to_research_contract": "Uses the fixed fixture dataset, split, baseline, metric, and evaluator unchanged.",
        "novelty_angle": "Potential model-level finding under the fixed benchmark.",
    }


class AgentDrivenIdeationTests(unittest.TestCase):
    def test_start_and_resume_compute_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            started = run_cli(
                target,
                "ideation",
                "start",
                "--run-id",
                "run-001",
                "--prompt",
                "fixture prompt",
                "--num-ideas",
                "2",
                "--reflection-budget",
                "5",
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertEqual(json.loads(started.stdout)["next_action"], "start_generator_batch")
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["research_contract"]["fixed_dataset"]["name"], "Fixture dataset")
            self.assertEqual(config["ideation"]["reflection_budget_per_idea"], 5)
            self.assertNotIn("reflection_budget", config["ideation"])
            self.assertEqual(config["ideation"]["max_attempts_per_slot"], 3)
            self.assertEqual(config["ideation"]["concurrency"]["max_subagents"], 6)
            scientist = config["ideation"]["modes"]["scientist"]
            self.assertEqual(scientist["generator_prompt"], "prompts/ideation/scientist/generator.md")
            self.assertEqual(scientist["critic_prompt"], "prompts/ideation/scientist/critic.md")
            self.assertEqual(scientist["ranker_prompt"], "prompts/ideation/scientist/ranker.md")
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["reflection_budget_per_idea"], 5)
            self.assertEqual(state["state"]["max_attempts_per_slot"], 3)

            resumed = run_cli(target, "ideation", "resume", "--run-id", "run-001", "--prompt")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            payload = json.loads(resumed.stdout)
            self.assertEqual(payload["next_action"], "start_generator_batch")
            self.assertIn("main Codex ideation orchestrator", payload["prompt"])
            self.assertIn("prompts/ideation/scientist/generator.md", payload["prompt"])
            self.assertTrue((target / ".ai-scientist" / "active-run.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "config.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").exists())

    def test_ideation_start_requires_run_owned_research_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            started = subprocess.run(
                [*CLI_ARGS, "--target-repo", str(target), "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(started.returncode, 0)
            self.assertIn("research_contract_required", started.stdout)

    def test_pending_intent_blocks_stop_hook_with_record_result_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            intent = run_cli(target, "ideation", "intent", "start", "--run-id", "run-001", "--role", "generator")
            self.assertEqual(intent.returncode, 0, intent.stderr)

            decision = evaluate_stop_decision(target)

            self.assertEqual(decision.decision, "block")
            self.assertIn("collect_subagent_results", decision.system_message)
            self.assertIn("Pending intents: 1", decision.system_message)

    def test_ideation_rejects_removed_modes_and_missing_prompt_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            removed = run_cli(target, "ideation", "start", "--run-id", "run-removed", "--prompt", "fixture", "--strictness-mode", "balanced")
            self.assertNotEqual(removed.returncode, 0)
            self.assertIn("invalid ideation mode", removed.stdout)

            (target / ".ai-scientist").mkdir()
            (target / ".ai-scientist" / "config.json").write_text(
                json.dumps(
                    {
                        "ideation": {
                            "modes": {
                                "custom": {
                                    "generator_prompt": "prompts/ideation/custom/missing.md",
                                    "critic_prompt": "prompts/ideation/custom/critic.md",
                                    "ranker_prompt": "prompts/ideation/custom/ranker.md",
                                }
                            }
                        }
                    }
                )
                + "\n"
            )
            missing = run_cli(target, "ideation", "start", "--run-id", "run-missing", "--prompt", "fixture", "--strictness-mode", "custom")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing ideation prompt file", missing.stdout)

    def test_ideation_start_freezes_prompt_paths_for_all_modes(self) -> None:
        for mode in ["scientist", "engineer", "custom"]:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                started = run_cli(target, "ideation", "start", "--run-id", f"run-{mode}", "--prompt", "fixture", "--strictness-mode", mode)
                self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
                config = json.loads((target / ".ai-scientist" / "runs" / f"run-{mode}" / "config.json").read_text())
                preset = config["ideation"]["modes"][mode]
                self.assertEqual(preset["generator_prompt"], f"prompts/ideation/{mode}/generator.md")
                self.assertEqual(preset["critic_prompt"], f"prompts/ideation/{mode}/critic.md")
                self.assertEqual(preset["ranker_prompt"], f"prompts/ideation/{mode}/ranker.md")

    def test_max_subagents_caps_generator_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            started = run_cli(
                target,
                "ideation",
                "start",
                "--run-id",
                "run-001",
                "--prompt",
                "fixture",
                "--strictness-mode",
                "engineer",
                "--num-ideas",
                "4",
                "--max-subagents",
                "3",
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            too_many = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "generator", "--count", "4")
            self.assertNotEqual(too_many.returncode, 0)
            self.assertIn("exceeds max_subagents 3", too_many.stdout)

            ok = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "generator", "--count", "3")
            self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
            payload = json.loads(ok.stdout)
            self.assertEqual(len(payload["intents"]), 3)
            self.assertEqual(payload["next_action"], "collect_subagent_results")

    def test_generator_batch_blocks_until_all_results_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "3").returncode, 0)
            batch = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "generator", "--count", "3")
            self.assertEqual(batch.returncode, 0, batch.stderr + batch.stdout)
            intents = json.loads(batch.stdout)["intents"]
            first = intents[0]
            completed = run_cli(
                target,
                "ideation",
                "intent",
                "complete",
                "--run-id",
                "run-001",
                "--intent-id",
                first["intent_id"],
                "--json",
                json.dumps(idea_payload(first["idea_id"])),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertEqual(json.loads(completed.stdout)["next_action"], "collect_subagent_results")
            self.assertIn("Pending intents: 2", evaluate_stop_decision(target).system_message)

            for intent in intents[1:]:
                proc = run_cli(
                    target,
                    "ideation",
                    "intent",
                    "complete",
                    "--run-id",
                    "run-001",
                    "--intent-id",
                    intent["intent_id"],
                    "--json",
                    json.dumps(idea_payload(intent["idea_id"])),
                )
                self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            resumed = run_cli(target, "ideation", "resume", "--run-id", "run-001")
            self.assertEqual(json.loads(resumed.stdout)["next_action"], "start_critic_batch")

    def test_path_first_intent_completion_reads_pending_result_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            batch = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "generator", "--count", "1")
            self.assertEqual(batch.returncode, 0, batch.stderr + batch.stdout)
            intent = json.loads(batch.stdout)["intents"][0]
            result_path = Path(intent["result_path"])
            self.assertTrue(result_path.exists())
            result_path.write_text(json.dumps(compact_payload(intent["idea_id"], "Path-first idea")) + "\n")

            completed = run_cli(target, "ideation", "intent", "complete", "--run-id", "run-001", "--intent-id", intent["intent_id"])

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["idea_states"][intent["idea_id"]]["latest_draft"]["title"], "Path-first idea")
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "logs" / "ideation-contract.json").exists())

    def test_stale_critic_hash_blocks_finalization_after_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            first = run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001", "First draft")))
            self.assertEqual(first.returncode, 0, first.stderr)
            critic = run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload()))
            self.assertEqual(critic.returncode, 0, critic.stderr)
            revised = run_cli(target, "idea", "revise-start", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "tighten idea")
            self.assertEqual(revised.returncode, 0, revised.stderr)
            second = run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(idea_payload("idea-001", "Second draft")))
            self.assertEqual(second.returncode, 0, second.stderr)

            finalized = run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001")

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("critic_stale_for_current_idea", finalized.stdout)

    def test_stale_critic_batch_intent_blocks_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            first = run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001", "First draft")))
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            batch = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "critic", "--idea-ids", "idea-001")
            self.assertEqual(batch.returncode, 0, batch.stderr + batch.stdout)
            intent_id = json.loads(batch.stdout)["intents"][0]["intent_id"]

            loop_state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            loop_state = json.loads(loop_state_path.read_text())
            idea = loop_state["state"]["idea_states"]["idea-001"]
            idea["latest_draft"] = idea_payload("idea-001", "Second draft")
            idea["draft_version"] = int(idea["draft_version"]) + 1
            idea["idea_hash"] = "stale-test-hash"
            loop_state_path.write_text(json.dumps(loop_state, indent=2, sort_keys=True) + "\n")

            completed = run_cli(
                target,
                "ideation",
                "intent",
                "complete",
                "--run-id",
                "run-001",
                "--intent-id",
                intent_id,
                "--json",
                json.dumps(critic_payload("ACCEPT", 82)),
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("critic_stale_for_current_idea", completed.stdout)

    def test_per_attempt_budget_blocks_revision_but_not_new_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "2", "--reflection-budget", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            revised = run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(critic_payload("REVISE", 62)))
            self.assertEqual(revised.returncode, 0, revised.stderr + revised.stdout)
            self.assertEqual(json.loads(revised.stdout)["next_action"], "revise_or_reject_batch")
            self.assertEqual(json.loads(revised.stdout)["next_action_details"]["required_action"], "idea exhaust")

            blocked = run_cli(target, "idea", "revise-start", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "try again")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("idea_reflection_budget_exhausted:idea-001", blocked.stdout)

            self.assertEqual(run_cli(target, "idea", "exhaust", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "reflection_budget_exhausted").returncode, 0)
            resumed = run_cli(target, "ideation", "resume", "--run-id", "run-001")
            self.assertEqual(json.loads(resumed.stdout)["next_action"], "start_generator_batch")
            self.assertEqual(json.loads(resumed.stdout)["next_action_details"]["next_idea_id"], "idea-002")

            premature = run_cli(target, "ideation", "complete", "--run-id", "run-001", "--budget-exhausted")
            self.assertNotEqual(premature.returncode, 0)
            self.assertIn("not all requested idea slots", premature.stdout)

    def test_reject_respawns_fresh_attempt_same_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(idea_payload("idea-001", "Rejected draft"))).returncode, 0)
            rejected = run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(critic_payload("REJECT", 25)))
            self.assertEqual(rejected.returncode, 0, rejected.stderr + rejected.stdout)
            payload = json.loads(rejected.stdout)
            self.assertEqual(payload["next_action"], "start_generator_batch")
            self.assertEqual(payload["next_action_details"]["idea_ids"], ["idea-001"])

            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            idea = state["state"]["idea_states"]["idea-001"]
            self.assertEqual(idea["status"], "fresh_attempt_requested")
            self.assertEqual(idea["attempt_index"], 2)
            self.assertEqual(idea["attempts_used"], 2)
            self.assertEqual(idea["reflection_count"], 0)
            self.assertEqual(len(idea["attempt_history"]), 1)
            self.assertNotIn("latest_draft", idea)
            self.assertNotIn("latest_critic", idea)

            batch = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "generator", "--idea-ids", "idea-001")
            self.assertEqual(batch.returncode, 0, batch.stderr + batch.stdout)
            intent = json.loads(batch.stdout)["intents"][0]
            fresh_payload = idea_payload("idea-001", "Fresh replacement")
            completed = run_cli(target, "ideation", "intent", "complete", "--run-id", "run-001", "--intent-id", intent["intent_id"], "--json", json.dumps(fresh_payload))
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            idea = state["state"]["idea_states"]["idea-001"]
            self.assertEqual(idea["latest_draft"]["title"], "Fresh replacement")
            self.assertEqual(idea["attempt_index"], 2)
            self.assertEqual(idea["reflection_count"], 1)

    def test_reject_attempt_cap_requires_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1", "--max-attempts-per-slot", "3").returncode, 0)
            for attempt in range(1, 4):
                self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(idea_payload("idea-001", f"Rejected draft {attempt}"))).returncode, 0)
                rejected = run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(critic_payload("REJECT", 20 + attempt)))
                self.assertEqual(rejected.returncode, 0, rejected.stderr + rejected.stdout)

            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            idea = state["state"]["idea_states"]["idea-001"]
            self.assertEqual(idea["status"], "fresh_attempt_requested")
            self.assertEqual(idea["budget_status"], "attempt_cap_reached")
            self.assertEqual(idea["attempts_used"], 3)
            self.assertEqual(len(idea["attempt_history"]), 3)
            cursor = json.loads(run_cli(target, "ideation", "resume", "--run-id", "run-001").stdout)
            self.assertEqual(cursor["next_action"], "revise_or_reject_batch")
            self.assertEqual(cursor["next_action_details"]["required_action"], "idea exhaust")

            blocked = run_cli(target, "ideation", "intent", "start-batch", "--run-id", "run-001", "--role", "generator", "--idea-ids", "idea-001")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("idea_attempt_cap_reached:idea-001", blocked.stdout)

            exhausted = run_cli(target, "idea", "exhaust", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "fresh_attempt_cap_reached")
            self.assertEqual(exhausted.returncode, 0, exhausted.stderr + exhausted.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["idea_states"]["idea-001"]["status"], "exhausted")

    def test_legacy_contract_fields_are_not_persisted_on_idea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            payload = compact_payload("idea-001", "Alias contract")
            payload["contract"] = payload.pop("research_contract")
            payload["contract"]["extra_nested"] = {"kept": True}

            drafted = run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(payload))

            self.assertEqual(drafted.returncode, 0, drafted.stderr + drafted.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertNotIn("research_contract", state["state"]["idea_states"]["idea-001"]["latest_draft"])
            self.assertNotIn("contract", state["state"]["idea_states"]["idea-001"]["latest_draft"])

    def test_accept_blocks_without_fit_to_research_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            payload = compact_payload("idea-001", "Missing fit")
            payload.pop("fit_to_research_contract")
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(payload)).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)

            finalized = run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001")

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("idea_fit_to_research_contract_required", finalized.stdout)

    def test_idea_that_changes_fixed_dataset_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            payload = compact_payload("idea-001", "Different dataset")
            payload["fixed_dataset"] = "another dataset"
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(payload)).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)

            finalized = run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001")

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("idea_changes_campaign_fixed_dataset", finalized.stdout)

    def test_idea_accepts_without_per_idea_research_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            payload = compact_payload("idea-001", "Performance idea")
            payload.pop("research_contract")
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(payload)).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)

            finalized = run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001")

            self.assertEqual(finalized.returncode, 0, finalized.stderr + finalized.stdout)

    def test_successful_engineer_ideation_validates_and_stop_hook_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            steps = [
                run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1"),
                run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))),
                run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 86))),
                run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001"),
                run_cli(target, "ideation", "complete", "--run-id", "run-001"),
            ]
            for step in steps:
                self.assertEqual(step.returncode, 0, step.stderr + step.stdout)

            ideas = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").read_text())["ideas"]
            self.assertEqual(ideas[0]["evaluation"], "ACCEPTED")
            self.assertIsNone(ideas[0]["rank"])
            validator = run_validator(target)
            self.assertEqual(validator.returncode, 0, validator.stderr)
            self.assertEqual(evaluate_stop_decision(target).decision, "allow")

    def test_compact_finalize_ready_and_ranker_intent_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            steps = [
                run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "2"),
                run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(compact_payload("idea-001", "Better idea", "family-a", score=90))),
                run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-002", "--json", json.dumps(compact_payload("idea-002", "Weaker idea", "family-b", score=70))),
                run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(critic_payload("ACCEPT", 86))),
                run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-002", "--json", json.dumps(critic_payload("ACCEPT", 84))),
                run_cli(target, "ideation", "finalize-ready", "--run-id", "run-001"),
            ]
            for step in steps:
                self.assertEqual(step.returncode, 0, step.stderr + step.stdout)

            ranked = run_cli(target, "ideation", "rank-candidates", "--run-id", "run-001")
            self.assertEqual(ranked.returncode, 0, ranked.stderr + ranked.stdout)
            ranked_payload = json.loads(ranked.stdout)
            intent = ranked_payload["intent"]
            self.assertEqual(intent["role"], "ranker")
            self.assertEqual(ranked_payload["next_action"], "collect_subagent_results")
            self.assertEqual(evaluate_stop_decision(target).decision, "block")

            completed_ranker = run_cli(
                target,
                "ideation",
                "intent",
                "complete",
                "--run-id",
                "run-001",
                "--intent-id",
                intent["intent_id"],
                "--json",
                json.dumps(
                    {
                        "selected_idea_id": "idea-001",
                        "rationale": "Better ranker-selected idea.",
                        "ranked_ideas": [
                            {"idea_id": "idea-001", "score": 91, "score_components": {"ranker": 91}, "rationale": "Best contract.", "risk_flags": []},
                            {"idea_id": "idea-002", "score": 70, "score_components": {"ranker": 70}, "rationale": "Weaker expected result.", "risk_flags": []},
                        ],
                    }
                ),
            )
            self.assertEqual(completed_ranker.returncode, 0, completed_ranker.stderr + completed_ranker.stdout)
            self.assertEqual(run_cli(target, "ideation", "complete", "--run-id", "run-001").returncode, 0)
            ideas = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").read_text())["ideas"]
            self.assertEqual(ideas[0]["id"], "idea-001")
            self.assertEqual(ideas[0]["rank"], 1)
            self.assertIn("minimum_command", ideas[0])
            self.assertNotIn("execution_plan", ideas[0]["normalized"])

    def test_unknown_runnable_command_blocks_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer").returncode, 0)
            payload = compact_payload("idea-001", "Bad command")
            payload["minimum_command"] = "python train.py"

            drafted = run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(payload))

            self.assertNotEqual(drafted.returncode, 0)
            self.assertIn("minimum_command_not_known_entrypoint", drafted.stdout)

    def test_semantic_scholar_cache_and_evidence_batch_atomicity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "2").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-002", "--json", json.dumps(idea_payload("idea-002"))).returncode, 0)
            evidence = {"data": [{"title": "Cached Paper", "citationCount": 1}]}
            first = run_cli(target, "idea", "search-semantic-scholar", "--run-id", "run-001", "--idea-id", "idea-001", "--query", "cache query", "--json", json.dumps(evidence))
            second = run_cli(target, "idea", "search-semantic-scholar", "--run-id", "run-001", "--idea-id", "idea-001", "--query", "cache query")
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)

            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            evidence_records = state["state"]["idea_states"]["idea-001"]["literature_evidence"]
            self.assertEqual([item["provenance"] for item in evidence_records], ["precomputed", "cache"])
            self.assertTrue(any((target / ".ai-scientist" / "evidence-cache" / "openalex").glob("*.json")))

            before_count = int(state["state"]["idea_states"]["idea-002"].get("literature_search_count") or 0)
            failed_batch = run_cli(
                target,
                "idea",
                "record-evidence-batch",
                "--run-id",
                "run-001",
                "--idea-ids",
                "idea-002",
                "missing-idea",
                "--queries",
                "q1",
                "q2",
                "--json",
                json.dumps(evidence),
            )
            self.assertNotEqual(failed_batch.returncode, 0)
            after_state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(int(after_state["state"]["idea_states"]["idea-002"].get("literature_search_count") or 0), before_count)

    def test_finalize_ready_blocks_duplicate_family_protocol_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "2").returncode, 0)
            duplicate_a = compact_payload("idea-001", "Duplicate A", "same-family")
            duplicate_b = compact_payload("idea-002", "Duplicate B", "same-family")
            duplicate_b["unique_protocol"] = duplicate_a["unique_protocol"]
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(duplicate_a)).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--idea-id", "idea-002", "--json", json.dumps(duplicate_b)).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--idea-id", "idea-002", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)

            finalized = run_cli(target, "ideation", "finalize-ready", "--run-id", "run-001")

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("duplicate_idea_family", finalized.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["idea_states"]["idea-001"]["status"], "critic_accepted")

    def test_ranking_not_required_when_candidate_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001").returncode, 0)

            completed = run_cli(target, "ideation", "complete", "--run-id", "run-001")

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["handoff"]["idea_batch"], ["idea-001"])

    def test_exhausted_no_candidate_is_terminal_but_fails_handoff_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("REJECT", 20))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "exhaust", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "critic rejected").returncode, 0)
            exhausted = run_cli(target, "ideation", "exhaust", "--run-id", "run-001")
            self.assertEqual(exhausted.returncode, 0, exhausted.stderr + exhausted.stdout)

            self.assertEqual(evaluate_stop_decision(target).decision, "allow")
            validator = run_validator(target)
            self.assertNotEqual(validator.returncode, 0)
            self.assertIn("researchable candidate", validator.stderr)

    def test_src_ideation_has_no_nested_codex_runner(self) -> None:
        ideation_src = SRC_DIR / "ideation"
        texts = [path.read_text() for path in ideation_src.rglob("*.py")]
        source_text = "\n".join(texts)
        subprocess_codex_lines = [
            line
            for text in texts
            for line in text.splitlines()
            if "subprocess." in line and "codex" in line.lower()
        ]

        self.assertFalse((ideation_src / "ideation_orchestrator_impl.py").exists())
        self.assertNotIn("CodexAgentRunner", source_text)
        self.assertEqual(subprocess_codex_lines, [])


if __name__ == "__main__":
    unittest.main()

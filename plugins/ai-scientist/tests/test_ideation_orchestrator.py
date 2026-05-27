from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PLUGIN_ROOT / "scripts"
SCRIPT = PLUGIN_ROOT / "scripts" / "ideation_orchestrator.py"
CLI = PLUGIN_ROOT / "scripts" / "ai_scientist_state_cli.py"
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate_run.py"
sys.path.insert(0, str(SCRIPT_DIR))

from ai_scientist_state import evaluate_stop_decision  # noqa: E402


def run_cli(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--target-repo", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def run_validator(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(target), "--gate", "ideation_to_research", "--run-id", "run-001"],
        text=True,
        capture_output=True,
        check=False,
    )


def idea_payload(idea_id: str, title: str = "Fixture idea") -> dict[str, object]:
    return {
        "id": idea_id,
        "title": title,
        "hypothesis": "Changing the model update rule will improve the benchmark score.",
        "expected_metric": "score",
        "risks": ["May not improve over baseline"],
        "novelty_rationale": "The combination has not been tested in this repository.",
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
        "unique_protocol": f"Run baseline, apply {title}, compare held-out score.",
        "expected_metric": "score",
        "smoke_runnable_now": True,
        "requires_implementation": [],
        "minimum_command": "uv run python -m pytest",
        "evidence_refs": [],
        "rubric_scores": {"performance": score, "feasibility": score, "repo_fit": score, "novelty": 40},
        "risk_flags": ["May not improve baseline"],
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
            self.assertEqual(config["ideation"]["concurrency"]["max_subagents"], 6)

            resumed = run_cli(target, "ideation", "resume", "--run-id", "run-001", "--prompt")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            payload = json.loads(resumed.stdout)
            self.assertEqual(payload["next_action"], "start_generator_batch")
            self.assertIn("main Codex ideation orchestrator", payload["prompt"])
            self.assertTrue((target / ".ai-scientist" / "active-run.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "config.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").exists())

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

    def test_successful_engineer_ideation_validates_and_stop_hook_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            steps = [
                run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1"),
                run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))),
                run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 86))),
                run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001"),
                run_cli(
                    target,
                    "ideation",
                    "rank-finalize",
                    "--run-id",
                    "run-001",
                    "--json",
                    json.dumps(
                        {
                            "selected_idea_id": "idea-001",
                            "ranked_ideas": [
                                {
                                    "idea_id": "idea-001",
                                    "score": 88,
                                    "score_components": {"performance": 45, "feasibility": 25, "repo_fit": 18},
                                    "rationale": "Best expected performance.",
                                }
                            ],
                        }
                    ),
                ),
                run_cli(target, "ideation", "complete", "--run-id", "run-001"),
            ]
            for step in steps:
                self.assertEqual(step.returncode, 0, step.stderr + step.stdout)

            ideas = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "ideas.json").read_text())["ideas"]
            self.assertEqual(ideas[0]["evaluation"], "ACCEPTED")
            self.assertEqual(ideas[0]["rank"], 1)
            validator = run_validator(target)
            self.assertEqual(validator.returncode, 0, validator.stderr)
            self.assertEqual(evaluate_stop_decision(target).decision, "allow")

    def test_compact_finalize_ready_and_deterministic_ranking(self) -> None:
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
                run_cli(target, "ideation", "rank-candidates", "--run-id", "run-001"),
                run_cli(target, "ideation", "complete", "--run-id", "run-001"),
            ]
            for step in steps:
                self.assertEqual(step.returncode, 0, step.stderr + step.stdout)

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
            self.assertTrue(any((target / ".ai-scientist" / "evidence-cache" / "semantic-scholar").glob("*.json")))

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

    def test_ranking_required_when_candidate_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("ACCEPT", 80))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "finalize", "--run-id", "run-001", "--idea-id", "idea-001").returncode, 0)

            completed = run_cli(target, "ideation", "complete", "--run-id", "run-001")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ranking must be finalized", completed.stdout)

    def test_exhausted_no_candidate_is_terminal_but_fails_handoff_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "ideation", "start", "--run-id", "run-001", "--prompt", "fixture", "--strictness-mode", "engineer", "--num-ideas", "1").returncode, 0)
            self.assertEqual(run_cli(target, "idea", "draft", "--run-id", "run-001", "--json", json.dumps(idea_payload("idea-001"))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "critic-record", "--run-id", "run-001", "--json", json.dumps(critic_payload("REJECT", 20))).returncode, 0)
            self.assertEqual(run_cli(target, "idea", "reject", "--run-id", "run-001", "--idea-id", "idea-001", "--reason", "critic rejected").returncode, 0)
            exhausted = run_cli(target, "ideation", "exhaust", "--run-id", "run-001")
            self.assertEqual(exhausted.returncode, 0, exhausted.stderr + exhausted.stdout)

            self.assertEqual(evaluate_stop_decision(target).decision, "allow")
            validator = run_validator(target)
            self.assertNotEqual(validator.returncode, 0)
            self.assertIn("researchable candidate", validator.stderr)

    def test_old_python_orchestrator_path_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--target-repo", str(target), "--prompt", "fixture"],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("retired", proc.stderr)
            self.assertFalse((SCRIPT_DIR / "ideation_orchestrator_impl.py").exists())
            self.assertNotIn("codex exec", SCRIPT.read_text())


if __name__ == "__main__":
    unittest.main()

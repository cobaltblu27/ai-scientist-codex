from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_ARGS = ["uv", "run", "--project", str(REPO_ROOT), "ai-scientist"]
VALIDATOR_ARGS = [*CLI_ARGS, "validate", "run"]
CRITIC_MODEL = "gpt-5.5"
CRITIC_EFFORT = "xhigh"


def fake_codex_bin(target: Path) -> Path:
    fake_bin = target / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    codex = fake_bin / "codex"
    if not codex.exists():
        codex.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys

primary = float(os.environ.get("AI_SCIENTIST_FAKE_USAGE_PRIMARY", "10"))
secondary = os.environ.get("AI_SCIENTIST_FAKE_USAGE_SECONDARY")
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("id") == 1:
        print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}), flush=True)
    if msg.get("id") == 2:
        limit = {
            "primary": {"usedPercent": primary, "windowDurationMins": 300, "resetsAt": "2026-05-28T12:00:00Z"},
            "planType": "test",
        }
        if secondary is not None:
            limit["secondary"] = {"usedPercent": float(secondary), "windowDurationMins": 10080, "resetsAt": "2026-05-29T12:00:00Z"}
        print(json.dumps({"jsonrpc": "2.0", "method": "notice", "params": {}}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"rateLimitsByLimitId": {"codex": limit}}}), flush=True)
        break
"""
        )
        codex.chmod(0o755)
    return fake_bin


def run_cli(
    target: Path,
    *args: str,
    usage_primary: float = 10,
    usage_secondary: float | None = None,
    inject_research_start_defaults: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_codex_bin(target)}{os.pathsep}{env.get('PATH', '')}"
    env["AI_SCIENTIST_FAKE_USAGE_PRIMARY"] = str(usage_primary)
    if usage_secondary is not None:
        env["AI_SCIENTIST_FAKE_USAGE_SECONDARY"] = str(usage_secondary)
    else:
        env.pop("AI_SCIENTIST_FAKE_USAGE_SECONDARY", None)
    argv = list(args)
    if inject_research_start_defaults and len(argv) >= 2 and argv[0] == "research" and argv[1] == "start":
        defaults = {
            "--strictness-mode": "scientist",
            "--selected-idea-id": "fixture-idea-001",
            "--target-venue-preset": "aaai_ijcai",
            "--target-venue-name": "AAAI",
            "--token-budget-percent": "95",
        }
        for flag, value in defaults.items():
            if flag not in argv:
                argv.extend([flag, value])
    return subprocess.run(
        [*CLI_ARGS, "--target-repo", str(target), *argv],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def run_validator(target: Path, gate: str = "research_to_review", run_id: str = "run-001") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*VALIDATOR_ARGS, str(target), "--gate", gate, "--run-id", run_id],
        text=True,
        capture_output=True,
        check=False,
    )


def write_baseline(target: Path, run_id: str = "run-001", score: float = 0.5) -> None:
    baseline = target / ".ai-scientist" / "runs" / run_id / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "command.log").write_text("baseline command ok\n")
    (baseline / "metrics.json").write_text(json.dumps({"score": score}) + "\n")


def accepted_node_payload(score: float = 0.8, novelty: dict | None = None) -> dict:
    node = {
        "benchmark_contract_version": "v1",
        "metrics": {"score": score},
        "split_integrity": {"pass": True, "summary": "same split as baseline"},
        "leakage_check": {"pass": True, "summary": "no leakage found"},
        "result_summary": "Improves the benchmark score over baseline.",
        "outcome_type": "practical_improvement",
        "strong_model_evidence": {
            "confirmation_trials": ["trial-001"],
            "tuning_plateau_or_exhausted": True,
            "cheap_improvements_remaining": False,
        },
        "mode_deliverables": {"builder": ["credible held-out score", "tuning disclosed"]},
        "trials": [
            {
                "trial_id": "trial-001",
                "purpose": "benchmark",
                "status": "completed",
                "command_ref": "nodes/node-001/trials/trial-001/command.json",
                "metrics": {"score": score},
                "benchmark_contract_version": "v1",
            }
        ],
    }
    if novelty is not None:
        node["novelty"] = novelty
    return {"node": node}


def research_contract() -> dict:
    return {
        "primary_hypothesis": "The intervention improves held-out score on the declared benchmark.",
        "success_criteria": "Accepted score beats baseline with clean split/leakage evidence.",
        "failure_criteria": "A controlled test proves the hypothesis does not hold under the declared benchmark.",
        "allowed_rescue_scope": "Only explicitly disclosed benchmark hygiene rescue findings are allowed.",
        "kill_criteria": "Stop when evidence cannot be produced without changing split, benchmark, or environment.",
        "metrics_that_matter": ["score"],
        "non_negotiable_comparisons": ["baseline", "declared split", "leakage check"],
    }


def paper_node_payload(score: float = 0.8, novelty: dict | None = None) -> dict:
    payload = accepted_node_payload(score=score, novelty=novelty)
    node = payload["node"]
    node.update(
        {
            "outcome_type": "hypothesis_supported",
            "current_claim": "The intervention improves held-out score on the declared benchmark.",
            "claim_equivalence": {"equivalent_to_original": True},
            "contract_evidence": {"success_criteria_met": True, "failure_criteria_met": False},
            "paper_worthiness": {"paper_worthy": True, "limitations": ["fixture"]},
            "mode_deliverables": {"scientist": ["reproducibility_note", "experiment_rationale", "split_leakage_evidence", "ablation_summary", "tuning_summary", "limitations"]},
        }
    )
    return payload


def failed_paper_node_payload(score: float = 0.4, novelty: dict | None = None) -> dict:
    payload = paper_node_payload(score=score, novelty=novelty or {"pass": True, "summary": "negative result is novel enough for fixture"})
    node = payload["node"]
    node.update(
        {
            "outcome_type": "hypothesis_failed_with_evidence",
            "current_claim": "The intervention fails under the declared controlled benchmark.",
            "claim_equivalence": {"equivalent_to_original": False, "reason": "negative resolution of the original hypothesis"},
            "contract_evidence": {
                "success_criteria_met": False,
                "failure_criteria_met": True,
                "routine_optimization_failure": False,
                "implementation_failure": False,
                "fundamental_failure_not_implementation_failure": True,
                "tested_conditions": ["declared split", "leakage check", "controlled baseline comparison"],
            },
            "alternative_approaches_considered": ["controlled baseline variant", "declared split sanity check"],
            "fundamental_failure_reason": "Controlled tests under the frozen contract show the original hypothesis does not hold.",
            "paper_worthiness": {"paper_worthy": True, "limitations": ["fixture negative-result evidence"]},
        }
    )
    return payload


def selection_payload(
    *,
    selected_node: str = "node-001",
    outcome_type: str = "practical_improvement",
    baseline_metric: float = 0.5,
    selected_metric: float = 0.8,
    rationale: str = "selected accepted node has strongest evidence",
) -> dict:
    return {
        "outcome_type": outcome_type,
        "metric_key": "score",
        "metric_direction": "maximize",
        "baseline_metric": baseline_metric,
        "selected_metric": selected_metric,
        "ranked_nodes": [{"node_id": selected_node, "selection_score": int(selected_metric * 100)}],
        "rejected_or_superseded": [],
        "rationale": rationale,
    }


def revision_payload(revision_id: str, alternative_count: int = 1) -> dict:
    alternatives = []
    for index in range(1, alternative_count + 1):
        alternatives.append(
            {
                "alternative_id": f"alt-{index:03d}",
                "title": f"alternative {index}",
                "scientific_rationale": "A different mechanism worth testing.",
                "expected_mechanism": "mechanism differs from the parent node",
                "venue_fit": "It can clear the frozen target venue bar with clean ablations.",
                "why_not_metric_hacking": "It keeps the frozen benchmark and split.",
                "why_not_claim_drift": "It preserves the selected idea's core claim.",
                "risk": "May underperform.",
            }
        )
    return {
        "node_id": "node-001",
        "revision_id": revision_id,
        "optimization_attempts": [{"change": "learning rate sweep", "metrics": {"best_score": 0.42}, "conclusion": "plateau"}],
        "useful_findings": ["same mechanism plateaued"],
        "why_current_direction_insufficient": "The current direction has insufficient evidence after local optimization.",
        "alternative_approaches": alternatives,
    }


def critic_payload(
    verdict: str = "ACCEPT",
    score: int = 85,
    *,
    role: str = "performance_auditor",
    mode: str = "builder",
    outcome_type: str = "practical_improvement",
) -> dict:
    payload = {
        "verdict": verdict,
        "mode": mode,
        "critic_role": role,
        "score": score,
        "rationale": f"{verdict} rationale with enough detail",
        "acceptance_checks": {
            "metric_contract_valid": True,
            "split_integrity_valid": True,
            "leakage_check_valid": True,
            "all_trials_accounted_for": True,
            "claim_matches_evidence": True,
            "mode_specific_bar_met": True,
            "cheap_improvements_remaining": False,
        },
        "missed_opportunity_scan": {
            "searched": ["hyperparameters", "data cleaning", "architecture"],
            "actionable_improvements": [],
            "why_remaining_ideas_are_not_worth_running": "fixture result has exhausted cheap improvements",
        },
        "strengths": ["clear benchmark evidence"],
        "weaknesses": ["limited scope"],
        "required_revisions": [],
        "risk_flags": [],
    }
    if mode in {"scientist", "researcher"} and role == "claim_critic":
        claim_fields = {
            "hypothesis_supported": {
                "original_hypothesis_verdict": "supported",
                "paper_worthy": True,
                "contract_success_met": True,
                "contract_failure_met": False,
                "rescue_scope_met": False,
                "fundamental_failure": False,
            },
            "hypothesis_failed_with_evidence": {
                "original_hypothesis_verdict": "failed",
                "paper_worthy": True,
                "contract_success_met": False,
                "contract_failure_met": True,
                "rescue_scope_met": False,
                "fundamental_failure": True,
            },
            "rescue_finding_with_failed_hypothesis": {
                "original_hypothesis_verdict": "rescue",
                "paper_worthy": True,
                "contract_success_met": False,
                "contract_failure_met": True,
                "rescue_scope_met": True,
                "fundamental_failure": True,
            },
        }
        payload.update(
            claim_fields.get(outcome_type, claim_fields["hypothesis_supported"])
        )
    if verdict == "REVISE":
        payload["required_revisions"] = ["add validation evidence"]
    return payload


def record_node_critic(
    target: Path,
    node_id: str = "node-001",
    verdict: str = "ACCEPT",
    run_id: str = "run-001",
    *,
    role: str | None = "performance_auditor",
    mode: str = "builder",
) -> subprocess.CompletedProcess[str]:
    args = ["node", "critic-start", "--run-id", run_id, "--node-id", node_id]
    if role:
        args.extend(["--role", role])
    started = run_cli(target, *args)
    if started.returncode != 0:
        return started
    started_payload = json.loads(started.stdout)
    spawned = run_cli(
        target,
        "node",
        "critic-spawn-record",
        "--run-id",
        run_id,
        "--critic-id",
        started_payload["critic_id"],
        "--agent-id",
        f"agent-{started_payload['critic_id']}",
        "--model",
        CRITIC_MODEL,
        "--reasoning-effort",
        CRITIC_EFFORT,
    )
    if spawned.returncode != 0:
        return spawned
    result_path = Path(json.loads(started.stdout)["result_path"])
    node_path = target / ".ai-scientist" / "runs" / run_id / "nodes" / node_id / "node.json"
    node = json.loads(node_path.read_text()) if node_path.exists() else {}
    result_path.write_text(json.dumps(critic_payload(verdict, role=started_payload["critic_role"], mode=mode, outcome_type=node.get("outcome_type", "practical_improvement"))) + "\n")
    return run_cli(target, "node", "critic-complete", "--run-id", run_id, "--critic-id", started_payload["critic_id"])


def accept_node_with_critic(target: Path, node_id: str = "node-001", payload: dict | None = None, run_id: str = "run-001") -> subprocess.CompletedProcess[str]:
    candidate = run_cli(
        target,
        "node",
        "transition",
        "--run-id",
        run_id,
        "--node-id",
        node_id,
        "--status",
        "candidate",
        "--json",
        json.dumps(payload or accepted_node_payload()),
    )
    if candidate.returncode != 0:
        return candidate
    return record_node_critic(target, node_id=node_id, verdict="ACCEPT", run_id=run_id)


def accept_paper_node_with_critics(target: Path, node_id: str = "node-001", payload: dict | None = None, run_id: str = "run-001", mode: str = "scientist") -> subprocess.CompletedProcess[str]:
    candidate = run_cli(
        target,
        "node",
        "transition",
        "--run-id",
        run_id,
        "--node-id",
        node_id,
        "--status",
        "candidate",
        "--json",
        json.dumps(payload or paper_node_payload(novelty={"pass": True, "summary": "novel"})),
    )
    if candidate.returncode != 0:
        return candidate
    first = record_node_critic(target, node_id=node_id, verdict="ACCEPT", run_id=run_id, role="evidence_auditor", mode=mode)
    if first.returncode != 0:
        return first
    return record_node_critic(target, node_id=node_id, verdict="ACCEPT", run_id=run_id, role="claim_critic", mode=mode)


class ResearchLoopV1Tests(unittest.TestCase):
    def test_research_start_requires_frozen_startup_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", inject_research_start_defaults=False)
            self.assertNotEqual(start.returncode, 0)
            self.assertIn("--strictness-mode", start.stdout)
            self.assertIn("--selected-idea-id", start.stdout)
            self.assertIn("--target-venue-preset", start.stdout)
            self.assertIn("--token-budget-percent", start.stdout)

    def test_research_start_freezes_target_venue_and_token_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(
                target,
                "research",
                "start",
                "--run-id",
                "run-001",
                "--strictness-mode",
                "researcher",
                "--selected-idea-id",
                "idea-abc",
                "--target-venue-preset",
                "aaai_ijcai",
                "--target-venue-name",
                "AAAI",
                "--target-venue-notes",
                "Needs clear mechanism and ablations.",
                "--token-budget-percent",
                "87",
                inject_research_start_defaults=False,
            )
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["selected_idea_id"], "idea-abc")
            self.assertEqual(config["research"]["selected_idea_id"], "idea-abc")
            self.assertEqual(config["research"]["target_venue"]["preset"], "aaai_ijcai")
            self.assertEqual(config["research"]["target_venue"]["name"], "AAAI")
            self.assertEqual(config["research"]["usage_cap"]["block_new_work_at_percent"], 87.0)
            self.assertEqual(config["research"]["usage_cap"]["cap_threshold_percent"], 87.0)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["selected_idea_id"], "idea-abc")
            self.assertEqual(state["state"]["target_venue"]["preset"], "aaai_ijcai")

    def test_compact_research_loop_validates_and_releases_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr)

            write_baseline(target)

            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--json",
                json.dumps({"state": {"baseline_status": "complete"}}),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)

            accepted = accept_node_with_critic(target)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            selected = run_cli(
                target,
                "selection",
                "finalize",
                "--selected-node",
                "node-001",
                "--json",
                json.dumps(selection_payload()),
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)

            audit = {
                "passed": True,
                "prompt_to_artifact_checklist": ["baseline exists", "node-001 accepted", "node-001 selected"],
                "verification_evidence": ["ai-scientist validate run --gate research_to_review"],
            }
            completed = run_cli(target, "research", "complete", "--json", json.dumps(audit))
            self.assertEqual(completed.returncode, 0, completed.stderr)

            validator = run_validator(target)
            self.assertEqual(validator.returncode, 0, validator.stderr)

            validation = run_cli(target, "validation", "record", "--gate", "research_to_review", "--exit-code", "0")
            self.assertEqual(validation.returncode, 0, validation.stderr)
            handoff = run_cli(target, "handoff", "record", "--gate", "research_to_review", "--exit-code", "0", "--approved")
            self.assertEqual(handoff.returncode, 0, handoff.stderr)

            active_run = target / ".ai-scientist" / "active-run.json"
            self.assertFalse(active_run.exists())
            journal = target / ".ai-scientist" / "runs" / "run-001" / "journal.jsonl"
            event_types = [json.loads(line)["event_type"] for line in journal.read_text().splitlines()]
            self.assertIn("state_transition", event_types)
            self.assertIn("validation", event_types)
            self.assertIn("handoff", event_types)

    def test_selection_finalize_requires_metric_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            accepted = accept_node_with_critic(target)
            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            incomplete = selection_payload()
            incomplete.pop("metric_direction")
            selected = run_cli(target, "selection", "finalize", "--selected-node", "node-001", "--json", json.dumps(incomplete))
            self.assertNotEqual(selected.returncode, 0)
            self.assertIn("selection finalize requires metric_direction", selected.stdout)

    def test_resume_returns_recorded_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["research"]["concurrency"]["max_subagents"], 6)
            self.assertEqual(config["research"]["usage_cap"]["warning_threshold_percent"], 85)
            self.assertEqual(config["research"]["usage_cap"]["cap_threshold_percent"], 95)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["usage_cap"]["effective_used_percent"], 10.0)
            updated = run_cli(
                target,
                "research",
                "set-next-action",
                "--lane",
                "node_work",
                "--node-id",
                "node-007",
                "--reason",
                "continue implementation review",
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)

            resumed = run_cli(target, "research", "resume")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            payload = json.loads(resumed.stdout)
            self.assertEqual(payload["next_action"], "node_work")
            self.assertEqual(payload["next_action_details"]["reason"], "continue implementation review")
            self.assertEqual(payload["next_action_details"]["subagent_concurrency_limit"], 6)
            self.assertIn("subagent_concurrency_source", payload["next_action_details"])
            self.assertEqual(payload["next_action_details"]["available_subagent_slots"], 6)

    def test_usage_check_fresh_and_force_polling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", usage_primary=10).returncode, 0)

            fresh = run_cli(target, "research", "usage-check", "--run-id", "run-001", usage_primary=96)
            self.assertEqual(fresh.returncode, 0, fresh.stderr + fresh.stdout)
            fresh_payload = json.loads(fresh.stdout)
            self.assertEqual(fresh_payload["usage_cap"]["effective_used_percent"], 10.0)
            self.assertFalse(fresh_payload["usage_cap"]["polled"])

            forced = run_cli(target, "research", "usage-check", "--run-id", "run-001", "--force", usage_primary=96)
            self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)
            forced_payload = json.loads(forced.stdout)
            self.assertEqual(forced_payload["usage_cap"]["effective_used_percent"], 96.0)
            self.assertTrue(forced_payload["usage_cap"]["capped"])

    def test_usage_warning_does_not_block_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", usage_primary=86)
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            resumed = run_cli(target, "research", "resume", "--run-id", "run-001", usage_primary=86)
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            payload = json.loads(resumed.stdout)
            self.assertEqual(payload["next_action"], "setup")
            self.assertEqual(payload["next_action_details"]["usage_cap"]["status"], "warning")

    def test_usage_cap_blocks_new_llm_work_and_not_resource_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", usage_primary=10).returncode, 0)
            forced = run_cli(target, "research", "usage-check", "--run-id", "run-001", "--force", usage_primary=96)
            self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)

            blocked = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-001",
                "--status",
                "running",
                usage_primary=96,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("blocked_on_usage_limit", blocked.stdout)

            node_blocked = run_cli(target, "node", "transition", "--run-id", "run-001", "--node-id", "node-001", "--status", "implementing")
            self.assertNotEqual(node_blocked.returncode, 0)
            self.assertIn("blocked_on_usage_limit", node_blocked.stdout)

            critic_blocked = run_cli(target, "node", "critic-start", "--run-id", "run-001", "--node-id", "node-001")
            self.assertNotEqual(critic_blocked.returncode, 0)
            self.assertIn("blocked_on_usage_limit", critic_blocked.stdout)

            resource = run_cli(
                target,
                "resource",
                "run",
                "--run-id",
                "run-001",
                "--node-id",
                "node-001",
                "--trial-id",
                "trial-001",
                "--",
                sys.executable,
                "-c",
                "print('resource ok')",
            )
            self.assertEqual(resource.returncode, 0, resource.stderr + resource.stdout)

    def test_no_limit_host_cap_logs_warning_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--no-limit-host-cap", usage_primary=96)
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            payload = json.loads(start.stdout)
            self.assertTrue(payload["usage_cap"]["capped"])
            self.assertTrue(payload["usage_cap"]["no_limit_host_cap"])
            allowed = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-001",
                "--status",
                "running",
                usage_primary=96,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr + allowed.stdout)

    def test_capped_resume_records_blocked_on_usage_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", usage_primary=10).returncode, 0)
            forced = run_cli(target, "research", "usage-check", "--run-id", "run-001", "--force", usage_primary=96)
            self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)
            resumed = run_cli(target, "research", "resume", "--run-id", "run-001", usage_primary=96)
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            payload = json.loads(resumed.stdout)
            self.assertEqual(payload["next_action"], "blocked_on_usage_limit")
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["phase_status"], "blocked_on_usage_limit")
            self.assertIn("blocked_reason", state)

    def test_research_subagent_concurrency_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--max-subagents", "2")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["research"]["concurrency"]["max_subagents"], 2)
            self.assertEqual(config["research"]["concurrency"]["source"], "research start --max-subagents")

            for subagent_id, node_id in (("worker-node-001", "node-001"), ("worker-node-002", "node-002")):
                proc = run_cli(
                    target,
                    "subagent",
                    "update",
                    "--run-id",
                    "run-001",
                    "--subagent-id",
                    subagent_id,
                    "--node-id",
                    node_id,
                    "--status",
                    "running",
                )
                self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            resumed = run_cli(target, "research", "resume", "--run-id", "run-001")
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            self.assertEqual(json.loads(resumed.stdout)["next_action_details"]["available_subagent_slots"], 0)

            blocked = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-003",
                "--node-id",
                "node-003",
                "--status",
                "running",
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("research subagent concurrency limit exceeded: 3 > 2", blocked.stdout)

            integrated = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-001",
                "--status",
                "integrated",
            )
            self.assertEqual(integrated.returncode, 0, integrated.stderr + integrated.stdout)
            allowed = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-003",
                "--node-id",
                "node-003",
                "--status",
                "running",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr + allowed.stdout)

    def test_research_concurrency_defaults_to_codex_max_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / ".codex").mkdir()
            (target / ".codex" / "config.toml").write_text("[agents]\nmax_threads = 3\n")

            start = run_cli(target, "research", "start", "--run-id", "run-001")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["research"]["concurrency"]["max_subagents"], 3)
            self.assertEqual(config["research"]["concurrency"]["source"], "codex [agents].max_threads")

            resumed = run_cli(target, "research", "resume", "--run-id", "run-001")
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            details = json.loads(resumed.stdout)["next_action_details"]
            self.assertEqual(details["available_subagent_slots"], 3)
            self.assertEqual(details["suggested_subagent_count"], 3)
            self.assertEqual(details["subagent_concurrency_source"], "codex [agents].max_threads")

    def test_research_subagent_update_reads_assigned_result_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            started = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-001",
                "--node-id",
                "node-001",
                "--status",
                "running",
            )
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            result_path = Path(json.loads(started.stdout)["result_path"])
            self.assertTrue(result_path.exists())
            result_path.write_text(json.dumps({"summary": "implemented approach", "workspace_path": "nodes/node-001/workspace"}) + "\n")

            completed = run_cli(
                target,
                "subagent",
                "update",
                "--run-id",
                "run-001",
                "--subagent-id",
                "worker-node-001",
                "--status",
                "completed_unintegrated",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            subagent = state["state"]["subagents"]["worker-node-001"]
            self.assertEqual(subagent["summary"], "implemented approach")
            self.assertEqual(subagent["result_path"], str(result_path))

    def test_node_transition_reads_assigned_result_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
            planned = run_cli(target, "node", "transition", "--run-id", "run-001", "--node-id", "node-001", "--status", "implementing")
            self.assertEqual(planned.returncode, 0, planned.stderr + planned.stdout)
            result_path = Path(json.loads(planned.stdout)["result_path"])
            self.assertTrue(result_path.exists())
            result_path.write_text(json.dumps(accepted_node_payload()) + "\n")

            candidate = run_cli(target, "node", "transition", "--run-id", "run-001", "--node-id", "node-001", "--status", "candidate")
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
            accepted = record_node_critic(target)

            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            node = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "nodes" / "node-001" / "node.json").read_text())
            self.assertEqual(node["metrics"]["score"], 0.8)
            self.assertEqual(node["result_path"], str(result_path))
            self.assertEqual(node["critic_verdict"], "ACCEPT")

    def test_resource_run_records_flat_trial_and_journal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            result = run_cli(
                target,
                "resource",
                "run",
                "--node-id",
                "node-001",
                "--trial-id",
                "trial-001",
                "--gpu",
                "--metrics-json",
                json.dumps({"score": 0.7}),
                "--",
                sys.executable,
                "-c",
                "print('resource ok')",
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            command_ref = Path(payload["command_ref"])
            command = json.loads(command_ref.read_text())
            self.assertEqual(command["exit_code"], 0)
            self.assertIn("stdout.log", command["stdout"])
            self.assertIn("command_spec_hash", command)
            self.assertEqual(command["env"]["CUDA_VISIBLE_DEVICES"], "0")
            self.assertTrue(command["resource_lease_id"])
            self.assertFalse((target / ".ai-scientist" / "runs" / "run-001" / "resources" / "gpu-0.lock").exists())

            node = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "nodes" / "node-001" / "node.json").read_text())
            self.assertEqual(node["trials"][0]["trial_id"], "trial-001")
            self.assertEqual(node["trials"][0]["metrics"]["score"], 0.7)
            self.assertEqual(node["trials"][0]["benchmark_contract_version"], "v1")
            self.assertEqual(node["trials"][0]["metrics_source"], "inline_metrics_json")
            self.assertEqual(node["trials"][0]["resource_lease_id"], command["resource_lease_id"])

            journal = target / ".ai-scientist" / "runs" / "run-001" / "journal.jsonl"
            events = [json.loads(line) for line in journal.read_text().splitlines()]
            self.assertTrue(any(event["event_type"] == "resource_event" and event.get("node_id") == "node-001" for event in events))

    def test_workspace_init_and_node_workspace_copy_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "train.py").write_text("print('train')\n")
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)

            workspace = run_cli(target, "workspace", "init", "--source", str(target))
            self.assertEqual(workspace.returncode, 0, workspace.stderr + workspace.stdout)
            baseline_workspace = target / ".ai-scientist" / "runs" / "run-001" / "baseline-workspace"
            self.assertTrue((baseline_workspace / "train.py").exists())
            self.assertFalse((baseline_workspace / ".ai-scientist").exists())

            node_workspace = run_cli(target, "node", "create-workspace", "--node-id", "node-001")
            self.assertEqual(node_workspace.returncode, 0, node_workspace.stderr + node_workspace.stdout)
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "nodes" / "node-001" / "workspace" / "train.py").exists())
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["workspace_plan_status"], "complete")
            self.assertEqual(state["state"]["nodes"]["node-001"]["status"], "planned")

    def test_scientist_mode_requires_passing_novelty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(
                run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "scientist", "--json", json.dumps({"research_contract": research_contract()})).returncode,
                0,
            )
            write_baseline(target)
            checkpoint = run_cli(target, "research", "checkpoint", "--json", json.dumps({"state": {"baseline_status": "complete"}}))
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            accepted = accept_paper_node_with_critics(target, payload=paper_node_payload(novelty={"pass": False, "summary": "not novel"}))
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            selected = run_cli(target, "selection", "finalize", "--selected-node", "node-001", "--json", json.dumps(selection_payload(outcome_type="hypothesis_supported")))
            self.assertEqual(selected.returncode, 0, selected.stderr)
            completed = run_cli(
                target,
                "research",
                "complete",
                "--json",
                json.dumps({"passed": True, "prompt_to_artifact_checklist": ["x"], "verification_evidence": ["x"]}),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            validator = run_validator(target)
            self.assertNotEqual(validator.returncode, 0)
            self.assertIn("novelty evidence must pass for scientist", validator.stderr)

    def test_candidate_node_cannot_be_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps({"node": {"result_summary": "candidate"}}))
            self.assertEqual(candidate.returncode, 0, candidate.stderr)
            selected = run_cli(target, "selection", "finalize", "--selected-node", "node-001", "--json", json.dumps({"ranked_nodes": [{"node_id": "node-001"}]}))
            self.assertNotEqual(selected.returncode, 0)
            self.assertIn("selected node must be accepted", selected.stdout)

    def test_direct_terminal_node_transition_requires_critic(self) -> None:
        for status in ("accepted", "invalid", "rejected"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
                direct = run_cli(
                    target,
                    "node",
                    "transition",
                    "--node-id",
                    "node-001",
                    "--status",
                    status,
                    "--json",
                    json.dumps(accepted_node_payload()),
                )
                self.assertNotEqual(direct.returncode, 0)
                self.assertIn(f"terminal node status {status} requires node critic-complete", direct.stdout)

    def test_critic_verdicts_drive_node_statuses(self) -> None:
        cases = [("ACCEPT", "accepted"), ("REVISE", "repairing"), ("INVALID", "invalid"), ("REJECT", "rejected")]
        for verdict, expected_status in cases:
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
                candidate = run_cli(
                    target,
                    "node",
                    "transition",
                    "--node-id",
                    "node-001",
                    "--status",
                    "candidate",
                    "--json",
                    json.dumps(accepted_node_payload()),
                )
                self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
                completed = record_node_critic(target, verdict=verdict)
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
                self.assertEqual(state["state"]["nodes"]["node-001"]["status"], expected_status)
                if verdict == "REVISE":
                    self.assertEqual(state["state"]["orchestrator"]["next_action"], "node_repair")
                    self.assertIn("repairs", state["state"])

    def test_critic_runtime_is_required_and_spawn_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
            candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload()))
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
            started = run_cli(target, "node", "critic-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            started_payload = json.loads(started.stdout)
            self.assertEqual(started_payload["required_model"], CRITIC_MODEL)
            self.assertEqual(started_payload["required_reasoning_effort"], CRITIC_EFFORT)

            result_path = Path(started_payload["result_path"])
            result_path.write_text(json.dumps(critic_payload("ACCEPT")) + "\n")
            missing_spawn = run_cli(target, "node", "critic-complete", "--critic-id", started_payload["critic_id"])
            self.assertNotEqual(missing_spawn.returncode, 0)
            self.assertIn("critic spawn metadata is required", missing_spawn.stdout)

    def test_critic_spawn_rejects_non_xhigh_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
            candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload()))
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)

            for args, expected in (
                (["--model", "gpt-5.4", "--reasoning-effort", CRITIC_EFFORT], "critic spawn model mismatch"),
                (["--model", CRITIC_MODEL, "--reasoning-effort", "medium"], "critic spawn reasoning effort mismatch"),
            ):
                started = run_cli(target, "node", "critic-start", "--node-id", "node-001")
                self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
                payload = json.loads(started.stdout)
                spawned = run_cli(
                    target,
                    "node",
                    "critic-spawn-record",
                    "--critic-id",
                    payload["critic_id"],
                    "--agent-id",
                    f"agent-{payload['critic_id']}",
                    *args,
                )
                self.assertNotEqual(spawned.returncode, 0)
                self.assertIn(expected, spawned.stdout)

    def test_accept_with_cheap_improvement_remaining_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
            candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload()))
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
            started = run_cli(target, "node", "critic-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            started_payload = json.loads(started.stdout)
            spawned = run_cli(
                target,
                "node",
                "critic-spawn-record",
                "--critic-id",
                started_payload["critic_id"],
                "--agent-id",
                "agent-cheap",
                "--model",
                CRITIC_MODEL,
                "--reasoning-effort",
                CRITIC_EFFORT,
            )
            self.assertEqual(spawned.returncode, 0, spawned.stderr + spawned.stdout)
            critic = critic_payload("ACCEPT")
            critic["acceptance_checks"]["cheap_improvements_remaining"] = True
            Path(started_payload["result_path"]).write_text(json.dumps(critic) + "\n")
            completed = run_cli(target, "node", "critic-complete", "--critic-id", started_payload["critic_id"])
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("cheap_improvements_remaining", completed.stdout)

    def test_revise_requires_worker_repair_before_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
            candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload()))
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
            revised = record_node_critic(target, verdict="REVISE")
            self.assertEqual(revised.returncode, 0, revised.stderr + revised.stdout)
            repair = json.loads(revised.stdout)["repair"]
            blocked = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload(score=0.81)))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("candidate transition requires completed worker repair payload", blocked.stdout)

            Path(repair["result_path"]).write_text(
                json.dumps(
                    {
                        "repair_id": repair["repair_id"],
                        "node_id": "node-001",
                        "files_changed": ["nodes/node-001/workspace/train.py"],
                        "commands_run": [],
                        "fixed_revisions": [],
                        "remaining_required_revisions": ["add validation evidence"],
                        "recommended_status": "candidate",
                    }
                )
                + "\n"
            )
            continued = run_cli(target, "node", "repair-complete", "--repair-id", repair["repair_id"])
            self.assertEqual(continued.returncode, 0, continued.stderr + continued.stdout)
            continued_payload = json.loads(continued.stdout)
            self.assertEqual(continued_payload["repair_status"], "continued")
            followup = continued_payload["followup_repair"]
            self.assertIsInstance(followup, dict)

            Path(followup["result_path"]).write_text(
                json.dumps(
                    {
                        "repair_id": followup["repair_id"],
                        "node_id": "node-001",
                        "files_changed": ["nodes/node-001/workspace/train.py"],
                        "commands_run": [],
                        "fixed_revisions": ["add validation evidence"],
                        "remaining_risks": [],
                        "recommended_status": "candidate",
                    }
                )
                + "\n"
            )
            completed = run_cli(target, "node", "repair-complete", "--repair-id", followup["repair_id"])
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            repaired_candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload(score=0.82)))
            self.assertEqual(repaired_candidate.returncode, 0, repaired_candidate.stderr + repaired_candidate.stdout)

    def test_scientist_research_can_complete_with_failed_hypothesis_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "scientist", "--json", json.dumps({"research_contract": research_contract()}))
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            write_baseline(target, score=0.5)
            checkpoint = run_cli(target, "research", "checkpoint", "--json", json.dumps({"state": {"baseline_status": "complete"}}))
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr + checkpoint.stdout)
            accepted = accept_paper_node_with_critics(target, payload=failed_paper_node_payload(score=0.4))
            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            selected = run_cli(
                target,
                "selection",
                "finalize",
                "--selected-node",
                "node-001",
                "--json",
                json.dumps(
                    selection_payload(
                        outcome_type="hypothesis_failed_with_evidence",
                        baseline_metric=0.5,
                        selected_metric=0.4,
                        rationale="ending with negative research result under the frozen contract",
                    )
                ),
            )
            self.assertEqual(selected.returncode, 0, selected.stderr + selected.stdout)
            audit = {
                "passed": True,
                "prompt_to_artifact_checklist": ["baseline exists", "node-001 accepted negative outcome", "node-001 selected"],
                "verification_evidence": ["ai-scientist validate run --gate research_to_review"],
            }
            completed = run_cli(target, "research", "complete", "--json", json.dumps(audit))
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            validator = run_validator(target)
            self.assertEqual(validator.returncode, 0, validator.stderr + validator.stdout)


    def test_plan_first_node_steps_keep_incomplete_work_unresolved_and_branchable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)

            plan_start = run_cli(
                target,
                "node",
                "plan-start",
                "--node-id",
                "node-001",
                "--json",
                json.dumps({"objective": "build a nontrivial model incrementally"}),
            )
            self.assertEqual(plan_start.returncode, 0, plan_start.stderr + plan_start.stdout)
            plan_id = json.loads(plan_start.stdout)["plan_id"]
            plan_payload = {
                "node_id": "node-001",
                "architecture_plan": {
                    "objective": "incremental model build",
                    "files_to_touch": ["model.py", "train.py"],
                    "implementation_steps": [
                        {"id": "step-001", "title": "create model shell", "instructions": "add model module", "done_check": "module imports"},
                        {"id": "step-002", "title": "train and evaluate", "instructions": "wire training loop", "done_check": "metrics recorded"},
                    ],
                    "done_definition": ["metrics.json produced", "split checks pass"],
                    "risks": ["partial implementation underperforms"],
                },
            }
            plan_complete = run_cli(target, "node", "plan-complete", "--plan-id", plan_id, "--json", json.dumps(plan_payload))
            self.assertEqual(plan_complete.returncode, 0, plan_complete.stderr + plan_complete.stdout)
            step_start = run_cli(target, "node", "step-start", "--node-id", "node-001")
            self.assertEqual(step_start.returncode, 0, step_start.stderr + step_start.stdout)
            step_id = json.loads(step_start.stdout)["step_id"]
            step_complete = run_cli(
                target,
                "node",
                "step-complete",
                "--step-id",
                step_id,
                "--json",
                json.dumps(
                    {
                        "node_id": "node-001",
                        "step_complete": False,
                        "done_definition_met": False,
                        "files_changed": ["model.py"],
                        "commands_run": ["python -m py_compile model.py"],
                        "remaining_work": ["training loop still missing"],
                        "optimization_attempts": [{"change": "smoke-test smaller hidden dim", "metrics": {"score": 0.41}, "conclusion": "same mechanism is still weak"}],
                        "spawned_node_ideas": [{"title": "smaller baseline", "rationale": "may validate data path faster"}],
                        "recommended_status": "implementing",
                    }
                ),
            )
            self.assertEqual(step_complete.returncode, 0, step_complete.stderr + step_complete.stdout)
            payload = json.loads(step_complete.stdout)
            self.assertEqual(payload["node_status"], "implementing")
            self.assertEqual(payload["next_action"], "node_implementation_step")
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["nodes"]["node-001"]["status"], "implementing")
            self.assertEqual(state["state"]["orchestrator"]["next_action"], "node_implementation_step")

            revision_start = run_cli(target, "node", "revision-start", "--node-id", "node-001")
            self.assertEqual(revision_start.returncode, 0, revision_start.stderr + revision_start.stdout)
            revision_start_payload = json.loads(revision_start.stdout)
            self.assertIn("AAAI", revision_start_payload["prompt"])
            revision_id = revision_start_payload["revision_id"]
            revision_payload = {
                "node_id": "node-001",
                "revision_id": revision_id,
                "optimization_attempts": [{"change": "smoke-test smaller hidden dim", "metrics": {"score": 0.41}, "conclusion": "plateaued"}],
                "useful_findings": ["training path works but same mechanism has weak signal"],
                "why_current_direction_insufficient": "The current same-mechanism variant is unlikely to clear the venue bar.",
                "alternative_approaches": [
                    {
                        "alternative_id": "alt-001",
                        "title": "mechanistic smaller baseline",
                        "scientific_rationale": "Different modeling assumption with clearer mechanism.",
                        "expected_mechanism": "regularized representation improves generalization",
                        "venue_fit": "Potentially clears the target venue by testing a clearer mechanism.",
                        "why_not_metric_hacking": "Keeps frozen split and declares all tuning.",
                        "why_not_claim_drift": "Still tests the selected idea's generalization mechanism.",
                        "risk": "May still underperform.",
                    }
                ],
            }
            revision_complete = run_cli(target, "node", "revision-complete", "--revision-id", revision_id, "--json", json.dumps(revision_payload))
            self.assertEqual(revision_complete.returncode, 0, revision_complete.stderr + revision_complete.stdout)
            critic_start = run_cli(target, "node", "revision-critic-start", "--revision-id", revision_id)
            self.assertEqual(critic_start.returncode, 0, critic_start.stderr + critic_start.stdout)
            critic_payload_started = json.loads(critic_start.stdout)
            self.assertIn("AAAI", critic_payload_started["prompt"])
            revision_critic = run_cli(
                target,
                "node",
                "revision-critic-complete",
                "--critic-id",
                critic_payload_started["critic_id"],
                "--json",
                json.dumps({"verdict": "BRANCH", "rationale": "alt-001 is viable and above the venue bar", "selected_alternative_ids": ["alt-001"], "venue_bar_assessment": "meets bar", "paper_worthiness_assessment": "worth trying", "drift_assessment": "no drift"}),
            )
            self.assertEqual(revision_critic.returncode, 0, revision_critic.stderr + revision_critic.stdout)

            branch = run_cli(
                target,
                "node",
                "branch",
                "--from-node",
                "node-001",
                "--node-id",
                "node-002",
                "--revision-id",
                revision_id,
                "--alternative-id",
                "alt-001",
                "--reason",
                "critic approved a different approach",
            )
            self.assertEqual(branch.returncode, 0, branch.stderr + branch.stdout)
            branch_payload = json.loads(branch.stdout)
            self.assertEqual(branch_payload["node_status"], "planning")

    def test_revision_start_requires_optimization_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            node = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "implementing")
            self.assertEqual(node.returncode, 0, node.stderr + node.stdout)
            revision = run_cli(target, "node", "revision-start", "--node-id", "node-001")
            self.assertNotEqual(revision.returncode, 0)
            self.assertIn("optimization_attempts", revision.stdout)

    def test_revision_alternatives_are_capped_at_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            node = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "implementing", "--json", json.dumps({"node": {"optimization_attempts": [{"change": "lr sweep", "metrics": {"score": 0.4}}]}}))
            self.assertEqual(node.returncode, 0, node.stderr + node.stdout)
            started = run_cli(target, "node", "revision-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            revision_id = json.loads(started.stdout)["revision_id"]
            too_many = run_cli(target, "node", "revision-complete", "--revision-id", revision_id, "--json", json.dumps(revision_payload(revision_id, alternative_count=4)))
            self.assertNotEqual(too_many.returncode, 0)
            self.assertIn("capped at 3", too_many.stdout)

    def test_continue_node_revision_blocks_branch_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            node = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "implementing", "--json", json.dumps({"node": {"optimization_attempts": [{"change": "lr sweep", "metrics": {"score": 0.4}}]}}))
            self.assertEqual(node.returncode, 0, node.stderr + node.stdout)
            started = run_cli(target, "node", "revision-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            revision_id = json.loads(started.stdout)["revision_id"]
            completed = run_cli(target, "node", "revision-complete", "--revision-id", revision_id, "--json", json.dumps(revision_payload(revision_id)))
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            critic_start = run_cli(target, "node", "revision-critic-start", "--revision-id", revision_id)
            self.assertEqual(critic_start.returncode, 0, critic_start.stderr + critic_start.stdout)
            critic_id = json.loads(critic_start.stdout)["critic_id"]
            critic_done = run_cli(target, "node", "revision-critic-complete", "--critic-id", critic_id, "--json", json.dumps({"verdict": "CONTINUE_NODE", "rationale": "needs more tuning before branching", "required_same_node_work": ["finish ablation"]}))
            self.assertEqual(critic_done.returncode, 0, critic_done.stderr + critic_done.stdout)
            branch = run_cli(target, "node", "branch", "--node-id", "node-002", "--from-node", "node-001", "--revision-id", revision_id, "--alternative-id", "alt-001")
            self.assertNotEqual(branch.returncode, 0)
            self.assertIn("BRANCH", branch.stdout)
            state = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text())
            self.assertEqual(state["state"]["nodes"]["node-001"]["status"], "implementing")

    def test_stop_drifted_blocks_further_branching_from_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            node = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "implementing", "--json", json.dumps({"node": {"optimization_attempts": [{"change": "lr sweep", "metrics": {"score": 0.4}}]}}))
            self.assertEqual(node.returncode, 0, node.stderr + node.stdout)
            started = run_cli(target, "node", "revision-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            revision_id = json.loads(started.stdout)["revision_id"]
            completed = run_cli(target, "node", "revision-complete", "--revision-id", revision_id, "--json", json.dumps(revision_payload(revision_id)))
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            critic_start = run_cli(target, "node", "revision-critic-start", "--revision-id", revision_id)
            self.assertEqual(critic_start.returncode, 0, critic_start.stderr + critic_start.stdout)
            critic_id = json.loads(critic_start.stdout)["critic_id"]
            critic_done = run_cli(target, "node", "revision-critic-complete", "--critic-id", critic_id, "--json", json.dumps({"verdict": "STOP_DRIFTED", "rationale": "alternatives are metric hacking below venue bar"}))
            self.assertEqual(critic_done.returncode, 0, critic_done.stderr + critic_done.stdout)
            branch = run_cli(target, "node", "branch", "--node-id", "node-002", "--from-node", "node-001", "--revision-id", revision_id, "--alternative-id", "alt-001")
            self.assertNotEqual(branch.returncode, 0)
            node_doc = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "nodes" / "node-001" / "node.json").read_text())
            self.assertEqual(node_doc["lineage_stop"]["verdict"], "STOP_DRIFTED")

    def test_findings_are_written_and_injected_into_node_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            finding = run_cli(target, "finding", "record", "--node-id", "node-000", "--kind", "optimization", "--summary", "wide layers failed but dropout helped", "--transferable")
            self.assertEqual(finding.returncode, 0, finding.stderr + finding.stdout)
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "findings.jsonl").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "findings.md").exists())
            plan = run_cli(target, "node", "plan-start", "--node-id", "node-001", "--json", json.dumps({"objective": "plan with memory"}))
            self.assertEqual(plan.returncode, 0, plan.stderr + plan.stdout)
            prompt = json.loads(plan.stdout)["prompt"]
            self.assertIn("wide layers failed but dropout helped", prompt)
            self.assertIn("AAAI", prompt)

    def test_scientist_failed_hypothesis_rejects_implementation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "scientist", "--json", json.dumps({"research_contract": research_contract()}))
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            payload = failed_paper_node_payload(score=0.4)
            payload["node"]["contract_evidence"]["implementation_failure"] = True
            payload["node"]["contract_evidence"]["fundamental_failure_not_implementation_failure"] = False
            accepted = accept_paper_node_with_critics(target, payload=payload)
            self.assertNotEqual(accepted.returncode, 0)
            self.assertIn("implementation failure", (accepted.stderr + accepted.stdout).lower())


    def test_stale_node_critic_result_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "builder").returncode, 0)
            candidate = run_cli(
                target,
                "node",
                "transition",
                "--node-id",
                "node-001",
                "--status",
                "candidate",
                "--json",
                json.dumps(accepted_node_payload(score=0.8)),
            )
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
            started = run_cli(target, "node", "critic-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            started_payload = json.loads(started.stdout)
            spawned = run_cli(
                target,
                "node",
                "critic-spawn-record",
                "--critic-id",
                started_payload["critic_id"],
                "--agent-id",
                "agent-stale",
                "--model",
                CRITIC_MODEL,
                "--reasoning-effort",
                CRITIC_EFFORT,
            )
            self.assertEqual(spawned.returncode, 0, spawned.stderr + spawned.stdout)
            update = run_cli(
                target,
                "node",
                "transition",
                "--node-id",
                "node-001",
                "--status",
                "candidate",
                "--json",
                json.dumps(accepted_node_payload(score=0.9)),
            )
            self.assertEqual(update.returncode, 0, update.stderr + update.stdout)
            result_path = Path(started_payload["result_path"])
            result_path.write_text(json.dumps(critic_payload("ACCEPT")) + "\n")
            completed = run_cli(target, "node", "critic-complete", "--critic-id", started_payload["critic_id"])
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("critic result is stale", completed.stdout)

    def test_research_completion_blocks_candidate_and_pending_critic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            write_baseline(target)
            checkpoint = run_cli(target, "research", "checkpoint", "--json", json.dumps({"state": {"baseline_status": "complete"}}))
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr + checkpoint.stdout)
            candidate = run_cli(target, "node", "transition", "--node-id", "node-001", "--status", "candidate", "--json", json.dumps(accepted_node_payload()))
            self.assertEqual(candidate.returncode, 0, candidate.stderr + candidate.stdout)
            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--json",
                json.dumps({"state": {"selected_node": "node-001", "selection": {"status": "final", "selected_node": "node-001"}}}),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr + checkpoint.stdout)
            audit = {"passed": True, "prompt_to_artifact_checklist": ["x"], "verification_evidence": ["x"]}
            completed = run_cli(target, "research", "complete", "--json", json.dumps(audit))
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("research_node_unresolved:node-001", completed.stdout)

            started = run_cli(target, "node", "critic-start", "--node-id", "node-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            completed = run_cli(target, "research", "complete", "--json", json.dumps(audit))
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("research_critics_pending", completed.stdout)

    def test_research_completion_blocks_terminal_node_without_critic_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            write_baseline(target)
            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--json",
                json.dumps(
                    {
                        "state": {
                            "baseline_status": "complete",
                            "nodes": {"node-001": {"status": "accepted"}},
                            "selected_node": "node-001",
                            "selection": {"status": "final", "selected_node": "node-001"},
                        }
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr + checkpoint.stdout)
            audit = {"passed": True, "prompt_to_artifact_checklist": ["x"], "verification_evidence": ["x"]}
            completed = run_cli(target, "research", "complete", "--json", json.dumps(audit))
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("research_node_missing_critic_ref:node-001", completed.stdout)

    def test_state_journal_mismatch_blocks_helper_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            updated = run_cli(target, "research", "set-next-action", "--lane", "node_work", "--reason", "create transition")
            self.assertEqual(updated.returncode, 0, updated.stderr)
            state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            state = json.loads(state_path.read_text())
            last_transition_id = state["last_transition_id"]
            journal = target / ".ai-scientist" / "runs" / "run-001" / "journal.jsonl"
            kept = [line for line in journal.read_text().splitlines() if last_transition_id not in line]
            journal.write_text("\n".join(kept) + "\n")

            blocked = run_cli(target, "research", "checkpoint", "--json", json.dumps({"state": {"baseline_status": "complete"}}))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("state_journal_mismatch", blocked.stdout)
            blocked_state = json.loads(state_path.read_text())
            self.assertEqual(blocked_state["phase_status"], "blocked_manual_recovery")
            active = json.loads((target / ".ai-scientist" / "active-run.json").read_text())
            self.assertEqual(active["status"], "blocked_manual_recovery")

    def test_stale_dead_pid_run_lock_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            lock = target / ".ai-scientist" / "runs" / "run-001" / "locks" / "run.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(json.dumps({"pid": 999999999, "created_at": "2026-01-01T00:00:00Z"}) + "\n")

            checkpoint = run_cli(target, "research", "checkpoint", "--json", json.dumps({"state": {"baseline_status": "complete"}}))
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr + checkpoint.stdout)
            self.assertFalse(lock.exists())

    def test_resume_blocks_when_next_action_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            state = json.loads(state_path.read_text())
            state["state"]["orchestrator"].pop("next_action")
            state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

            resumed = run_cli(target, "research", "resume")
            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn("orchestrator.next_action", resumed.stdout)


if __name__ == "__main__":
    unittest.main()

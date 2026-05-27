from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PLUGIN_ROOT / "scripts"
CLI = SCRIPT_DIR / "ai_scientist_state_cli.py"
VALIDATOR = SCRIPT_DIR / "validate_run.py"


def run_cli(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--target-repo", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def run_validator(target: Path, gate: str = "research_to_review", run_id: str = "run-001") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(target), "--gate", gate, "--run-id", run_id],
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


class ResearchLoopV1Tests(unittest.TestCase):
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

            accepted = run_cli(
                target,
                "node",
                "transition",
                "--node-id",
                "node-001",
                "--status",
                "accepted",
                "--json",
                json.dumps(accepted_node_payload()),
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            selected = run_cli(
                target,
                "selection",
                "finalize",
                "--selected-node",
                "node-001",
                "--json",
                json.dumps({"ranked_nodes": [{"node_id": "node-001", "selection_score": 80}]}),
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)

            audit = {
                "passed": True,
                "prompt_to_artifact_checklist": ["baseline exists", "node-001 accepted", "node-001 selected"],
                "verification_evidence": ["validate_run.py --gate research_to_review"],
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

    def test_resume_returns_recorded_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001").returncode, 0)
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["research"]["concurrency"]["max_subagents"], 6)
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
            self.assertEqual(payload["next_action_details"]["available_subagent_slots"], 6)

    def test_research_subagent_concurrency_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--max-subagents", "2")
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            config = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "config.json").read_text())
            self.assertEqual(config["research"]["concurrency"]["max_subagents"], 2)

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

            accepted = run_cli(target, "node", "transition", "--run-id", "run-001", "--node-id", "node-001", "--status", "accepted")

            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            node = json.loads((target / ".ai-scientist" / "runs" / "run-001" / "nodes" / "node-001" / "node.json").read_text())
            self.assertEqual(node["metrics"]["score"], 0.8)
            self.assertEqual(node["result_path"], str(result_path))

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
            self.assertEqual(run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "scientist").returncode, 0)
            write_baseline(target)
            checkpoint = run_cli(target, "research", "checkpoint", "--json", json.dumps({"state": {"baseline_status": "complete"}}))
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            accepted = run_cli(
                target,
                "node",
                "transition",
                "--node-id",
                "node-001",
                "--status",
                "accepted",
                "--json",
                json.dumps(accepted_node_payload()),
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            selected = run_cli(target, "selection", "finalize", "--selected-node", "node-001", "--json", json.dumps({"ranked_nodes": [{"node_id": "node-001"}]}))
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
            lock.parent.mkdir(parents=True)
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

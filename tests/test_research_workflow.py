from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_support import AI_SCIENTIST_CMD, REPO_ROOT, read_json


def run_cli(target: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*AI_SCIENTIST_CMD, "--target-repo", str(target), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def json_out(proc: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(proc.stdout + proc.stderr) from exc


class ResearchWorkflowTests(unittest.TestCase):
    def test_skill_and_prompt_layout_exists(self) -> None:
        skill = REPO_ROOT / "skills" / "research-loop" / "SKILL.md"
        self.assertTrue(skill.exists())
        skill_text = skill.read_text()
        self.assertIn("research_contract", skill_text)
        self.assertIn("CLI_Command_Map", skill_text)
        self.assertIn("The orchestrator must not implement the node directly", skill_text)
        self.assertIn("first return must be a plan", skill_text)
        self.assertIn("Resource-Heavy Runs", skill_text)
        legacy = REPO_ROOT / "skills" / "research-loop-legacy" / "SKILL.md"
        self.assertTrue(legacy.exists())
        self.assertIn("name: research-loop-legacy", legacy.read_text())
        for mode in ["scientist", "engineer", "custom"]:
            self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / mode / "critic.md").exists())
            self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / mode / "revision-worker.md").exists())
        self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / "orchestrator.md").exists())
        self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / "worker.md").exists())
        self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / "baseline-worker.md").exists())
        orchestrator = (REPO_ROOT / "prompts" / "research-loop" / "orchestrator.md").read_text()
        worker = (REPO_ROOT / "prompts" / "research-loop" / "worker.md").read_text()
        baseline_worker = (REPO_ROOT / "prompts" / "research-loop" / "baseline-worker.md").read_text()
        self.assertIn("Frozen_Arguments", orchestrator)
        self.assertIn("Checkpoint_Guide", orchestrator)
        self.assertIn("Subagent_Model", orchestrator)
        self.assertIn("Baseline_Unit", orchestrator)
        self.assertIn("research checkpoint", orchestrator)
        self.assertIn("Do not start editing", orchestrator)
        self.assertIn("Checkpoint the worker assignment", orchestrator)
        self.assertIn("first return must be a plan", worker)
        self.assertIn("fixed_split_dir", worker)
        self.assertIn("target_threshold", worker)
        self.assertIn("baseline/splits", baseline_worker)
        self.assertIn("baseline/baseline.json", baseline_worker)

    def test_rejects_removed_modes_and_requires_custom_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for mode in ["researcher", "balanced", "builder"]:
                proc = run_cli(target, "research", "start", "--run-id", f"run-{mode}", "--strictness-mode", mode, "--selected-idea-id", "idea-001")
                self.assertNotEqual(proc.returncode, 0)

            custom = run_cli(target, "research", "start", "--run-id", "run-custom", "--strictness-mode", "custom", "--selected-idea-id", "idea-001")
            self.assertNotEqual(custom.returncode, 0)
            self.assertIn("custom_criteria", custom.stdout)

    def test_start_checkpoint_select_complete_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            contract = {
                "primary_hypothesis": "Fixture hypothesis",
                "goal_type": "performance",
                "success_criteria": {"metric": "score", "min": 0.75},
                "failure_criteria": {"max_score": 0.5},
                "allowed_rescue_scope": "same benchmark only",
                "kill_criteria": "leakage or missing baseline",
                "non_drift_definition": "do not change the benchmark",
                "metrics_that_matter": ["score"],
                "non_negotiable_comparisons": ["baseline"],
                "baseline_reference": {"name": "Fixture baseline"},
                "benchmark_plan": {"command": "run benchmark"},
                "target_threshold": {"score": 0.75},
            }
            payload = {
                "resources": {"max_parallel": 1},
                "selected_idea": {"id": "idea-001", "title": "Fixture", "research_contract": contract},
                "arguments": {"python_environment": "uv", "target_venue": "fixture venue"},
            }
            start = run_cli(
                target,
                "research",
                "start",
                "--run-id",
                "run-001",
                "--strictness-mode",
                "scientist",
                "--selected-idea-id",
                "idea-001",
                "--json",
                json.dumps(payload),
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            cfg = read_json(target / ".ai-scientist" / "runs" / "run-001" / "config.json")
            self.assertEqual(cfg["research_contract"], contract)
            self.assertEqual(cfg["arguments"]["mode"], "scientist")
            self.assertEqual(cfg["arguments"]["python_environment"], "uv")
            self.assertEqual(cfg["arguments"]["target_venue"], "fixture venue")
            self.assertEqual(cfg["arguments"]["target_idea"]["id"], "idea-001")
            self.assertEqual(cfg["research"]["baseline_worker_prompt"], "prompts/research-loop/baseline-worker.md")
            self.assertTrue((target / ".ai-scientist" / "runs" / "run-001" / "baseline").exists())

            removed_task = run_cli(target, "research", "task-start", "--run-id", "run-001", "--task-id", "task-001", "--kind", "critic")
            self.assertNotEqual(removed_task.returncode, 0)

            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--run-id",
                "run-001",
                "--json",
                json.dumps(
                    {
                        "nodes": {
                            "node-001": {
                                "node_id": "node-001",
                                "status": "accepted",
                                "summary": "accepted fixture",
                                "evidence_refs": ["journal"],
                            }
                        },
                        "orchestrator": {"next_action": "select"},
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)

            select = run_cli(
                target,
                "research",
                "select",
                "--run-id",
                "run-001",
                "--node-id",
                "node-001",
                "--summary",
                "accepted fixture",
                "--evidence-ref",
                "journal",
                "--acceptance-rationale",
                "critic accepted",
            )
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)

            audit = {"passed": True, "prompt_to_artifact_checklist": ["selected accepted node"], "verification_evidence": ["unit fixture"]}
            done = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

            validate = subprocess.run(
                [*AI_SCIENTIST_CMD, "validate", "run", str(target), "--gate", "research_to_review", "--run-id", "run-001"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

    def test_checkpoint_work_records_are_resume_and_completion_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(
                target,
                "research",
                "start",
                "--run-id",
                "run-001",
                "--strictness-mode",
                "scientist",
                "--selected-idea-id",
                "idea-001",
                "--json",
                json.dumps({"resources": {"max_parallel": 1}, "selected_idea": {"id": "idea-001", "title": "Fixture"}}),
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--run-id",
                "run-001",
                "--json",
                json.dumps(
                    {
                        "work": {"worker-node-001": {"kind": "worker", "node_id": "node-001", "status": "running"}},
                        "nodes": {"node-001": {"node_id": "node-001", "status": "accepted", "summary": "accepted fixture"}},
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            resume = run_cli(target, "research", "resume", "--run-id", "run-001")
            self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)
            self.assertIn("worker-node-001", json_out(resume)["open_work"])

            select = run_cli(target, "research", "select", "--run-id", "run-001", "--node-id", "node-001", "--summary", "accepted fixture")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
            audit = {"passed": True, "prompt_to_artifact_checklist": ["selected accepted node"], "verification_evidence": ["unit fixture"]}
            blocked = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("research_work_unresolved", blocked.stdout)

    def test_baseline_checkpoint_resume_and_completion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(
                target,
                "research",
                "start",
                "--run-id",
                "run-001",
                "--strictness-mode",
                "scientist",
                "--selected-idea-id",
                "idea-001",
                "--json",
                json.dumps({"resources": {"max_parallel": 1}, "selected_idea": {"id": "idea-001", "title": "Fixture"}}),
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--run-id",
                "run-001",
                "--json",
                json.dumps(
                    {
                        "baseline": {
                            "required": True,
                            "status": "preparing_split",
                            "fixed_split_dir": ".ai-scientist/runs/run-001/baseline/splits",
                            "split_manifest_ref": ".ai-scientist/runs/run-001/baseline/baseline.json",
                            "baseline_score_refs": [],
                            "repo_refs": [],
                        },
                        "work": {"baseline-worker-001": {"kind": "baseline-worker", "status": "completed"}},
                        "nodes": {"node-001": {"node_id": "node-001", "status": "accepted", "summary": "accepted fixture"}},
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            resume = run_cli(target, "research", "resume", "--run-id", "run-001")
            self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)
            self.assertEqual(json_out(resume)["baseline"]["status"], "preparing_split")
            select = run_cli(target, "research", "select", "--run-id", "run-001", "--node-id", "node-001", "--summary", "accepted fixture")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
            audit = {"passed": True, "prompt_to_artifact_checklist": ["selected accepted node"], "verification_evidence": ["unit fixture"]}
            blocked = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("research_baseline_not_ready", blocked.stdout)

            ready = run_cli(
                target,
                "research",
                "checkpoint",
                "--run-id",
                "run-001",
                "--json",
                json.dumps({"baseline": {"required": True, "status": "ready"}}),
            )
            self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
            done = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_resource_caps_missing_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(target, "research", "start", "--run-id", "run-001", "--strictness-mode", "engineer", "--selected-idea-id", "idea-001")
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            acquire = run_cli(target, "resource", "acquire", "--run-id", "run-001", "--task-id", "task-001", "--gpus", "1")
            self.assertNotEqual(acquire.returncode, 0)
            self.assertIn("resource_caps_missing", acquire.stdout)

    def test_resource_acquire_wait_release_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            start = run_cli(
                target,
                "research",
                "start",
                "--run-id",
                "run-001",
                "--strictness-mode",
                "engineer",
                "--selected-idea-id",
                "idea-001",
                "--json",
                json.dumps({"resources": {"max_parallel": 1, "gpus": 1, "cpu_cores": 2, "memory_mb": 2048}}),
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            first = run_cli(target, "resource", "acquire", "--run-id", "run-001", "--task-id", "task-001", "--gpus", "1")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            lease_id = json_out(first)["lease"]["lease_id"]

            blocked = run_cli(target, "resource", "acquire", "--run-id", "run-001", "--task-id", "task-002", "--gpus", "1", "--timeout-sec", "0")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("resource_unavailable", blocked.stdout)

            release = run_cli(target, "resource", "release", "--run-id", "run-001", "--lease-id", lease_id)
            self.assertEqual(release.returncode, 0, release.stdout + release.stderr)

            run = run_cli(
                target,
                "resource",
                "run",
                "--run-id",
                "run-001",
                "--task-id",
                "baseline-score-001",
                "--",
                sys.executable,
                "-c",
                "print('resource ok')",
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            command_ref = Path(json_out(run)["command_ref"])
            self.assertTrue(command_ref.exists())
            self.assertIn("logs/resources/baseline-score-001", str(command_ref))
            command = read_json(command_ref)
            self.assertEqual(command["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()

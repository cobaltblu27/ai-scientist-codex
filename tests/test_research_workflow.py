from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_support import AI_SCIENTIST_CMD, REPO_ROOT, read_json


def research_contract() -> dict[str, object]:
    return {
        "primary_hypothesis": "The intervention improves held-out score on the declared benchmark.",
        "goal_type": "performance",
        "success_criteria": {"metric": "score", "min": 0.75},
        "failure_criteria": {"max_score": 0.5},
        "allowed_rescue_scope": "same benchmark only",
        "kill_criteria": "leakage or missing baseline",
        "non_drift_definition": "do not change the benchmark",
        "metrics_that_matter": ["score"],
        "non_negotiable_comparisons": ["baseline"],
        "baseline_reference": {"title": "Fixture baseline", "usability": "Defines the comparable score."},
        "benchmark_plan": {"command": "run benchmark"},
        "target_threshold": {"score": 0.75},
        "fixed_dataset": "fixture dataset",
        "fixed_split": "fixture split",
        "fixed_baseline": "fixture baseline",
        "evaluator_command": "run benchmark",
    }


def selected_idea_payload(resources: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "selected_idea": {"id": "idea-001", "title": "Fixture", "research_contract": research_contract()},
    }
    if resources is not None:
        payload["resources"] = resources
    return payload


def run_cli(target: Path, *args: str, input_text: str | None = None, extra_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    command_args = list(args)
    if len(command_args) >= 2 and command_args[0] == "research" and command_args[1] == "start":
        if "--json" in command_args:
            index = command_args.index("--json") + 1
            payload = json.loads(command_args[index])
            if not isinstance(payload, dict):
                raise AssertionError("test research start payload must be object")
            if "idea_batch" not in payload:
                selected = payload.get("selected_idea")
                if isinstance(selected, dict):
                    selected.setdefault("id", "idea-001")
                    selected.setdefault("title", "Fixture")
                    selected.setdefault("research_contract", research_contract())
                else:
                    payload.setdefault("selected_idea", {"id": "idea-001", "title": "Fixture", "research_contract": research_contract()})
            command_args[index] = json.dumps(payload)
        elif "--json-file" not in command_args:
            command_args.extend(["--json", json.dumps(selected_idea_payload())])
    env = os.environ.copy()
    if extra_path is not None:
        env["PATH"] = os.pathsep.join([str(extra_path), env.get("PATH", "")])
    return subprocess.run(
        [*AI_SCIENTIST_CMD, "--target-repo", str(target), *command_args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
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
        self.assertIn("default scheduler is local", skill_text)
        self.assertIn("--scheduler slurm", skill_text)
        self.assertIn("Orchestrator_Instructions", skill_text)
        self.assertIn("This `SKILL.md` is the orchestrator instruction source", skill_text)
        self.assertIn("Do not load or rely on a separate orchestrator prompt file", skill_text)
        self.assertIn("Critic_Revision_Flow", skill_text)
        self.assertIn("Branching", skill_text)
        self.assertIn("Research completion is two-stage", skill_text)
        self.assertIn("custom criteria remain the acceptance standard", skill_text)
        self.assertIn("allowed_rescue_scope", skill_text)
        self.assertIn("kill_criteria", skill_text)
        self.assertIn("baseline/baseline.json` for the run-level authoritative", skill_text)
        self.assertIn(".ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/", skill_text)
        self.assertIn("git rev-parse HEAD", skill_text)
        self.assertIn("git worktree", skill_text)
        self.assertIn("workspace_artifact_links", skill_text)
        self.assertIn("copy_with_symlinks", skill_text)
        self.assertIn("Terminal work statuses are `completed`, `cancelled`, `failed`, `abandoned`, `accepted`, and `rejected`", skill_text)
        self.assertIn("--gpus <n> --cpu-cores <n> --memory-mb <n> --timeout-sec <seconds> --poll-sec <seconds>", skill_text)
        self.assertIn("revision_critic_ref", skill_text)
        self.assertIn("safe to implement or branch from; it does not mean the node itself is accepted", skill_text)
        legacy = REPO_ROOT / "skills" / "research-loop-legacy" / "SKILL.md"
        self.assertTrue(legacy.exists())
        self.assertIn("name: research-loop-legacy", legacy.read_text())
        revision_skill = REPO_ROOT / "skills" / "revision-brainstorm" / "SKILL.md"
        self.assertTrue(revision_skill.exists())
        self.assertIn("branch_from_node", revision_skill.read_text())
        for mode in ["scientist", "engineer", "custom"]:
            critic_path = REPO_ROOT / "prompts" / "research-loop" / mode / "critic.md"
            revision_path = REPO_ROOT / "prompts" / "research-loop" / mode / "revision-worker.md"
            self.assertTrue(critic_path.exists())
            self.assertTrue(revision_path.exists())
            critic_text = critic_path.read_text()
            self.assertIn("revision plan", critic_text)
            self.assertIn("does not accept the node", critic_text)
            self.assertIn("revision-brainstorm", revision_path.read_text())
        self.assertFalse((REPO_ROOT / "prompts" / "research-loop" / "orchestrator.md").exists())
        self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / "worker.md").exists())
        self.assertTrue((REPO_ROOT / "prompts" / "research-loop" / "baseline-worker.md").exists())
        orchestrator = skill_text
        worker = (REPO_ROOT / "prompts" / "research-loop" / "worker.md").read_text()
        baseline_worker = (REPO_ROOT / "prompts" / "research-loop" / "baseline-worker.md").read_text()
        self.assertIn("Arguments", orchestrator)
        self.assertIn("Checkpoint_Guide", orchestrator)
        self.assertIn("Subagents", orchestrator)
        self.assertIn("Baseline_Unit", orchestrator)
        self.assertIn("research checkpoint", orchestrator)
        self.assertIn("Do not start editing", orchestrator)
        self.assertIn("Checkpoint the worker assignment", orchestrator)
        self.assertIn("parent_node_id", orchestrator)
        self.assertIn("fresh accepting critic verdict", orchestrator)
        self.assertIn("Research completion is two-stage", orchestrator)
        self.assertIn("custom criteria remain the acceptance standard", orchestrator)
        self.assertIn("revision_critic_ref", orchestrator)
        self.assertIn("agent_thread_id", orchestrator)
        self.assertIn("git rev-parse HEAD", orchestrator)
        self.assertIn("workspace_artifact_links", orchestrator)
        self.assertIn("Terminal work statuses", orchestrator)
        self.assertIn("--gpus 1 --cpu-cores 4 --memory-mb 8192 --timeout-sec 3600 --poll-sec 30", orchestrator)
        self.assertIn("first return must be a plan", worker)
        self.assertIn("fixed_split_dir", worker)
        self.assertIn("target_threshold", worker)
        self.assertIn("custom_criteria", worker)
        self.assertIn("baseline/baseline.json", worker)
        self.assertIn("workspace_artifact_links", worker)
        self.assertIn("report a blocker", worker)
        self.assertIn("baseline/splits", baseline_worker)
        self.assertIn("baseline/baseline.json", baseline_worker)
        self.assertIn("run-level authoritative baseline manifest", baseline_worker)

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
            self.assertEqual(cfg["research"]["orchestrator_prompt"], "skills/research-loop/SKILL.md")
            self.assertEqual(cfg["research"]["baseline_worker_prompt"], "prompts/research-loop/baseline-worker.md")
            self.assertEqual(cfg["research"]["revision_brainstorm_skill"], "skills/revision-brainstorm/SKILL.md")
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
                                "critic_ref": ".ai-scientist/runs/run-001/logs/critics/node-001/critic-001/verdict.json",
                                "critic_verdict": "ACCEPT_FINAL",
                                "critic_completed_at": "2026-01-01T00:00:00Z",
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

    def test_campaign_start_freezes_idea_batch_and_learning_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            payload = {
                "resources": {"max_parallel": 1},
                "research_contract": research_contract(),
                "idea_batch": [
                    {"id": "idea-001", "title": "First idea", "fit_to_research_contract": "fixed benchmark"},
                    {"id": "idea-002", "title": "Second idea", "fit_to_research_contract": "fixed benchmark"},
                ],
                "arguments": {"python_environment": "uv"},
            }
            start = run_cli(
                target,
                "research",
                "start",
                "--run-id",
                "run-campaign",
                "--strictness-mode",
                "engineer",
                "--json",
                json.dumps(payload),
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            cfg = read_json(target / ".ai-scientist" / "runs" / "run-campaign" / "config.json")
            self.assertTrue(cfg["campaign_mode"])
            self.assertIsNone(cfg["selected_idea_id"])
            self.assertEqual([idea["id"] for idea in cfg["idea_batch"]], ["idea-001", "idea-002"])
            self.assertEqual(cfg["research_contract"], payload["research_contract"])
            state = read_json(target / ".ai-scientist" / "runs" / "run-campaign" / "loop-state.json")
            self.assertEqual([idea["id"] for idea in state["state"]["idea_batch"]], ["idea-001", "idea-002"])
            self.assertEqual(state["state"]["resource_queue"], {"pending": [], "released": [], "completed": []})
            notes_ref = Path(cfg["learning_notes_ref"])
            self.assertTrue(notes_ref.exists())
            checkpoint = run_cli(
                target,
                "research",
                "checkpoint",
                "--run-id",
                "run-campaign",
                "--json",
                json.dumps(
                    {
                        "nodes": {
                            "node-001": {
                                "node_id": "node-001",
                                "seed_idea_id": "idea-001",
                                "status": "accepted",
                                "summary": "accepted campaign node",
                                "critic_ref": ".ai-scientist/runs/run-campaign/logs/critics/node-001/critic-001/verdict.json",
                                "critic_verdict": "ACCEPT_FINAL",
                                "critic_completed_at": "2026-01-01T00:00:00Z",
                            }
                        }
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            select = run_cli(target, "research", "select", "--run-id", "run-campaign", "--node-id", "node-001", "--summary", "accepted campaign node")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
            audit = {"passed": True, "prompt_to_artifact_checklist": ["selected accepted node"], "verification_evidence": ["unit fixture"]}
            done = run_cli(target, "research", "complete", "--run-id", "run-campaign", "--json", json.dumps(audit))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            validate = subprocess.run(
                [*AI_SCIENTIST_CMD, "validate", "run", str(target), "--gate", "research_to_review", "--run-id", "run-campaign"],
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
                        "nodes": {
                            "node-001": {
                                "node_id": "node-001",
                                "status": "accepted",
                                "summary": "accepted fixture",
                                "critic_ref": ".ai-scientist/runs/run-001/logs/critics/node-001/critic-001/verdict.json",
                                "critic_verdict": "ACCEPT",
                                "critic_completed_at": "2026-01-01T00:00:00Z",
                            }
                        },
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

    def test_revision_work_and_branch_metadata_checkpoint(self) -> None:
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
                        "work": {
                            "revision-node-002": {
                                "kind": "revision-worker",
                                "node_id": "node-002",
                                "status": "completed",
                                "prompt_path": "prompts/research-loop/engineer/revision-worker.md",
                                "skill_path": "skills/revision-brainstorm/SKILL.md",
                                "result_ref": ".ai-scientist/runs/run-001/logs/revisions/node-002/revision-node-002/result.json",
                            },
                            "revision-critic-node-002": {
                                "kind": "revision-critic",
                                "node_id": "node-002",
                                "status": "completed",
                                "prompt_path": "prompts/research-loop/engineer/critic.md",
                                "result_ref": ".ai-scientist/runs/run-001/logs/critics/node-002/revision-critic-node-002/verdict.json",
                            },
                        },
                        "nodes": {
                            "node-001": {"node_id": "node-001", "status": "rejected", "summary": "weak parent"},
                            "node-002": {
                                "node_id": "node-002",
                                "status": "planning",
                                "parent_node_id": "node-001",
                                "branch_reason": "failed experiments suggested a narrower implementation path within the contract",
                                "branch_source_evidence_refs": [".ai-scientist/runs/run-001/logs/workers/node-001/result.json"],
                                "revision_plan_ref": ".ai-scientist/runs/run-001/logs/revisions/node-002/revision-node-002/result.json",
                            },
                        },
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            state = read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")
            node = state["state"]["nodes"]["node-002"]
            self.assertEqual(node["parent_node_id"], "node-001")
            self.assertIn("branch_source_evidence_refs", node)
            self.assertEqual(state["state"]["work"]["revision-node-002"]["skill_path"], "skills/revision-brainstorm/SKILL.md")

    def test_completion_requires_fresh_accept_critic_for_selected_node(self) -> None:
        audit = {"passed": True, "prompt_to_artifact_checklist": ["selected accepted node"], "verification_evidence": ["unit fixture"]}
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
                json.dumps({"nodes": {"node-001": {"node_id": "node-001", "status": "accepted", "summary": "accepted fixture"}}}),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            select = run_cli(target, "research", "select", "--run-id", "run-001", "--node-id", "node-001", "--summary", "accepted fixture")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
            blocked = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("research_node_missing_critic_ref:node-001", blocked.stdout)

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
                        "nodes": {
                            "node-001": {
                                "node_id": "node-001",
                                "status": "accepted",
                                "summary": "accepted fixture",
                                "critic_ref": ".ai-scientist/runs/run-001/logs/critics/node-001/critic-001/verdict.json",
                                "critic_verdict": "REVISE",
                                "critic_completed_at": "2026-01-01T00:00:00Z",
                            }
                        }
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            select = run_cli(target, "research", "select", "--run-id", "run-001", "--node-id", "node-001", "--summary", "accepted fixture")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
            blocked = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("research_node_critic_verdict_invalid:node-001:REVISE", blocked.stdout)

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
                        "nodes": {
                            "node-001": {
                                "node_id": "node-001",
                                "status": "accepted",
                                "summary": "accepted fixture",
                                "metric": 0.75,
                                "critic_ref": ".ai-scientist/runs/run-001/logs/critics/node-001/critic-001/verdict.json",
                                "critic_verdict": "ACCEPT",
                                "critic_completed_at": "2026-01-01T00:00:00Z",
                            }
                        }
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            stale = run_cli(
                target,
                "research",
                "checkpoint",
                "--run-id",
                "run-001",
                "--json",
                json.dumps({"nodes": {"node-001": {"metric": 0.8}}}),
            )
            self.assertEqual(stale.returncode, 0, stale.stdout + stale.stderr)
            select = run_cli(target, "research", "select", "--run-id", "run-001", "--node-id", "node-001", "--summary", "accepted fixture")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
            blocked = run_cli(target, "research", "complete", "--run-id", "run-001", "--json", json.dumps(audit))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("research_node_critic_stale:node-001", blocked.stdout)

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
                        "nodes": {
                            "node-001": {
                                "node_id": "node-001",
                                "status": "accepted",
                                "summary": "accepted fixture",
                                "critic_ref": ".ai-scientist/runs/run-001/logs/critics/node-001/critic-001/verdict.json",
                                "critic_verdict": "ACCEPT",
                                "critic_completed_at": "2026-01-01T00:00:00Z",
                            }
                        }
                    }
                ),
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stdout + checkpoint.stderr)
            state = read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")
            node = state["state"]["nodes"]["node-001"]
            self.assertEqual(node["critic_evidence_fingerprint"], node["node_evidence_fingerprint"])
            select = run_cli(target, "research", "select", "--run-id", "run-001", "--node-id", "node-001", "--summary", "accepted fixture")
            self.assertEqual(select.returncode, 0, select.stdout + select.stderr)
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
            self.assertEqual(command["scheduler"], "local")

    def test_resource_run_slurm_backend_records_scheduler_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            fake_sbatch = fake_bin / "sbatch"
            fake_sbatch.write_text(
                f"""#!{sys.executable}
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
stdout_path = None
stderr_path = None
script = args[-1]
i = 0
while i < len(args):
    arg = args[i]
    if arg == "--output":
        stdout_path = args[i + 1]
        i += 2
    elif arg.startswith("--output="):
        stdout_path = arg.split("=", 1)[1]
        i += 1
    elif arg == "--error":
        stderr_path = args[i + 1]
        i += 2
    elif arg.startswith("--error="):
        stderr_path = arg.split("=", 1)[1]
        i += 1
    else:
        i += 1

print("12345")
stdout_handle = Path(stdout_path).open("w") if stdout_path else subprocess.DEVNULL
stderr_handle = Path(stderr_path).open("w") if stderr_path else subprocess.DEVNULL
try:
    proc = subprocess.run(["bash", script], stdout=stdout_handle, stderr=stderr_handle, check=False)
finally:
    if hasattr(stdout_handle, "close"):
        stdout_handle.close()
    if hasattr(stderr_handle, "close"):
        stderr_handle.close()
raise SystemExit(proc.returncode)
"""
            )
            fake_sbatch.chmod(0o755)

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
                json.dumps(
                    {
                        "resources": {
                            "max_parallel": 1,
                            "gpus": 1,
                            "cpu_cores": 8,
                            "memory_mb": 32768,
                            "scheduler": {
                                "type": "slurm",
                                "partition": "gpu",
                                "time": "00:10:00",
                                "gres": "gpu:1",
                                "cpus_per_task": 2,
                                "mem": "4G",
                            },
                        }
                    }
                ),
                extra_path=fake_bin,
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

            run = run_cli(
                target,
                "resource",
                "run",
                "--run-id",
                "run-001",
                "--task-id",
                "baseline-score-001",
                "--gpus",
                "1",
                "--cpu-cores",
                "2",
                "--memory-mb",
                "4096",
                "--metrics-json",
                json.dumps({"score": 0.9}),
                "--",
                sys.executable,
                "-c",
                "print('slurm resource ok')",
                extra_path=fake_bin,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            payload = json_out(run)
            self.assertTrue(payload["lease_id"].startswith("lease-"))
            command = read_json(Path(payload["command_ref"]))
            self.assertEqual(command["scheduler"], "slurm")
            self.assertEqual(command["slurm_job_id"], "12345")
            self.assertEqual(command["exit_code"], 0)
            self.assertEqual(command["scheduler_exit_code"], 0)
            self.assertEqual(command["resource_lease_id"], payload["lease_id"])
            self.assertEqual(command["metrics"]["score"], 0.9)
            self.assertIn("--wait", command["sbatch_argv"])
            self.assertIn("--gres=gpu:1", command["sbatch_argv"])
            self.assertEqual(command["slurm"]["partition"], "gpu")
            self.assertIn("slurm resource ok", Path(command["stdout"]).read_text())

            state = read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")
            resources = state["state"]["resources"]
            self.assertNotIn(payload["lease_id"], resources["leases"])
            self.assertEqual(resources["completed_leases"][payload["lease_id"]]["status"], "completed")
            self.assertEqual(resources["completed_leases"][payload["lease_id"]]["details"]["slurm_job_id"], "12345")

    def test_resource_run_slurm_submission_failure_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            fake_sbatch = fake_bin / "sbatch"
            fake_sbatch.write_text(
                f"""#!{sys.executable}
import sys

print("submission failed", file=sys.stderr)
raise SystemExit(7)
"""
            )
            fake_sbatch.chmod(0o755)

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
                json.dumps({"resources": {"max_parallel": 1, "gpus": 1, "scheduler": {"type": "slurm", "partition": "gpu"}}}),
                extra_path=fake_bin,
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            run = run_cli(
                target,
                "resource",
                "run",
                "--run-id",
                "run-001",
                "--task-id",
                "baseline-score-001",
                "--gpus",
                "1",
                "--",
                sys.executable,
                "-c",
                "print('should not run')",
                extra_path=fake_bin,
            )
            self.assertNotEqual(run.returncode, 0)
            payload = json_out(run)
            command = read_json(Path(payload["command_ref"]))
            self.assertEqual(command["scheduler"], "slurm")
            self.assertEqual(command["scheduler_exit_code"], 7)
            self.assertEqual(command["exit_code"], 7)
            self.assertIn("submission failed", command["sbatch_stderr"])
            state = read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")
            resources = state["state"]["resources"]
            self.assertNotIn(payload["lease_id"], resources["leases"])
            self.assertEqual(resources["completed_leases"][payload["lease_id"]]["status"], "failed")


if __name__ == "__main__":
    unittest.main()

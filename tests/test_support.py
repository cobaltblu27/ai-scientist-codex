from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
PLUGIN_ROOT = REPO_ROOT
AI_SCIENTIST_CMD = ["uv", "run", "--project", str(REPO_ROOT), "ai-scientist"]
VALIDATE_RUN_ARGS = [*AI_SCIENTIST_CMD, "validate", "run"]

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_python(args: list[str | Path], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*map(str, args)],
        cwd=cwd or REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def make_idea_json(tmp_path: Path) -> Path:
    path = tmp_path / "idea.json"
    write_json(
        path,
        {
            "id": "fixture-idea",
            "title": "Fixture research improvement",
            "summary": "Improve a deterministic toy metric without touching source data.",
            "hypothesis": "The fixture runner can produce a better candidate metric.",
        },
    )
    return path


def make_research_target(tmp_path: Path) -> Path:
    target = tmp_path / "research-target"
    target.mkdir(parents=True)
    (target / "GUIDELINES.md").write_text(
        "# Fixture target\nPreserve train/test split and never mutate files outside .ai-scientist.\n"
    )
    write_json(target / "data" / "split-manifest.json", {"train": [1, 2], "test": [3], "policy": "fixed"})
    (target / "baseline.py").write_text(
        """
import argparse, json
parser = argparse.ArgumentParser()
parser.add_argument('--metrics-out', required=True)
parser.add_argument('--metric-key', default='accuracy')
parser.add_argument('--value', type=float, default=0.50)
args = parser.parse_args()
with open(args.metrics_out, 'w') as fh:
    json.dump({args.metric_key: args.value, 'score': args.value}, fh)
""".lstrip()
    )
    return target


def write_minimal_research_run(target: Path, *, decision: str | None = "approved", direction: str = "maximize") -> Path:
    """Create a compact final-validation fixture matching the v4 research artifact contract."""
    ai = target / ".ai-scientist"
    run = ai / "runs" / "run-001"
    node = run / "nodes" / "node-001"
    write_json(ai / "config.json", {"strictness_mode": "engineer", "target_repo": str(target), "resources": {"max_parallel": 1}})
    write_json(ai / "ideas" / "ideas.json", {"ideas": [{"id": "fixture-idea", "title": "Fixture"}]})
    metric_key = "accuracy" if direction == "maximize" else "loss"
    baseline_value = 0.50 if direction == "maximize" else 0.50
    candidate_value = 0.70 if direction == "maximize" else 0.30
    write_json(run / "research-plan.json", {"metric_key": metric_key, "metric_direction": direction, "strictness_mode": "engineer"})
    write_json(run / "dependency-plan.json", {"planned_dependencies": []})
    write_json(run / "dependency-status.json", {"status": "approved", "dependencies": []})
    (run / "api-ledger.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (run / "api-ledger.jsonl").write_text(json.dumps({"kind": "fixture", "external_calls": 0}) + "\n")
    write_json(run / "principles.json", {"principles": [{"id": "p1", "gates": ["research_to_review"], "evidence_artifacts": ["research-plan.json"]}]})
    write_json(run / "baseline" / "metrics.json", {metric_key: baseline_value, "score": baseline_value})
    (run / "baseline" / "command.log").write_text("baseline ok\n")
    write_json(run / "baseline" / "split_integrity.json", {"passed": True})
    write_json(run / "baseline" / "leakage_check.json", {"passed": True})
    write_json(run / "baseline" / "runtime-mutation-check.json", {"passed": True, "changed_paths": []})
    write_json(run / "baseline" / "resource_usage.json", {"requested": {}, "enforced": {}})
    write_json(node / "node.json", {"node_id": "node-001", "action": "improve", "strictness_mode": "engineer", "status": "completed"})
    write_json(node / "prompt.json", {"action": "improve", "strictness_mode": "engineer", "node_id": "node-001", "template_id": "improve", "template_version": "1", "metric_contract": {"metric_key": metric_key, "metric_direction": direction}})
    write_json(node / "metrics.json", {metric_key: candidate_value, "score": candidate_value})
    (node / "command.log").write_text("node ok\n")
    write_json(node / "split_integrity.json", {"passed": True})
    write_json(node / "leakage_check.json", {"passed": True})
    write_json(node / "result_summary.json", {"summary": "candidate improved"})
    write_json(node / "mode_deliverables.json", {"engineer": {"rationale": True, "split_leakage_evidence": True, "result_summary": True}})
    write_json(node / "runtime-mutation-check.json", {"passed": True, "changed_paths": []})
    write_json(node / "resource_usage.json", {"requested": {"gpus": 1}, "enforced": {"gpus": 1}})
    write_json(run / "selection.json", {"selected_node": "node-001", "metric_key": metric_key, "metric_direction": direction, "baseline_metric": baseline_value, "selected_metric": candidate_value, "comparison": ">" if direction == "maximize" else "<", "threshold_passed": True})
    (run / "dispatcher-events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
        {"event": "enqueue", "node_id": "node-001"},
        {"event": "start", "node_id": "node-001"},
        {"event": "finish", "node_id": "node-001"},
    ]))
    write_json(run / "journal.json", {"events": [{"event": "finalized"}]})
    from legacy.research_loop_v1.handoff import artifact_snapshot

    snapshot = artifact_snapshot(run)
    validation = {"gate": "research_to_review", "validation_mode": "evidence", "exit_code": 0, "selected_node": "node-001", "metric_key": metric_key, "metric_direction": direction, "artifact_snapshot": snapshot}
    write_json(run / "run-status.json", {"strictness_mode": "engineer", "last_validation": validation, "last_validations": {"research_to_review": validation}})
    (run / "handoff.jsonl").write_text(json.dumps({"gate": "research_to_review", "from_phase": "research", "to_phase": "review", "approved": True, "validator_exit_code": 0, "approved_at": "2026-05-07T00:00:00Z", "artifact_snapshot": snapshot}) + "\n")
    write_json(run / "verifier-decision.json", {"decision": "go", "blockers": []})
    if decision is not None:
        write_json(
            run / "verifier-decisions" / "research_to_review.json",
            {
                "decision": decision,
                "gate": "research_to_review",
                "artifact_snapshot": snapshot,
                "validation_command": "ai-scientist validate run --gate research_to_review --validation-mode evidence",
            },
        )
    return run

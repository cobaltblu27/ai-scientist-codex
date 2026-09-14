#!/usr/bin/env python3
"""Generate a deterministic `.ai-scientist/` tree, shaped per docs/SCHEMA.md, for the dashboard.

Usage: python3 tests/fixtures/dashboard/make_fixture.py [--out DIR]
Then:  ai-scientist --target-repo tests/fixtures/dashboard dashboard --open

Every file gets a fixed content and a fixed mtime, so two runs of this script
produce byte-identical trees and the scanner's ordering is stable in tests.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

T0 = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)

IDEATION_RUN = "20260910-ideation-cifar10"
RESEARCH_RUN = "20260912-research-cifar10"
SUCCESS_RUN = "20260905-research-housing-success"
EXHAUSTED_RUN = "20260901-research-energy-exhausted"
BLOCKED_RUN = "20260911-research-ogbn-blocked"
BROKEN_RUN = "20260913-broken-loop-state"

RUN_IDS = [RESEARCH_RUN, SUCCESS_RUN, EXHAUSTED_RUN, BLOCKED_RUN, IDEATION_RUN, BROKEN_RUN]

# Message ids in the research run's message box (docs/SCHEMA.md 3.11).
MSG_N2_PENDING = "msg-20260912T095600Z-7c1e"
MSG_N1_ACK = "msg-20260912T093000Z-2b9d"
MSG_N3_REJECTED = "msg-20260912T091000Z-e4a0"


def ts(minutes_ago: float) -> str:
    return (T0 - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def write(path: Path, data, *, at: str | None = None) -> None:
    """Write JSON or text and pin the file's mtime to `at` (ISO) or T0."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2) + "\n")
    stamp = _epoch(at or ts(0))
    os.utime(path, (stamp, stamp))


def contract(goal: str, dataset: str, metric: str, direction: str, threshold: float) -> dict:
    return {
        "contract_id": dataset,
        "title": goal,
        "goal": goal,
        "dataset": {"name": dataset, "version": "1.0"},
        "split_protocol": "official train/test split, 10% of train held out for validation, seed 13",
        "primary_metric": metric,
        "primary_metric_direction": direction,
        "success_threshold": threshold,
        "evaluator_command": "python eval.py --split test",
    }


CIFAR = contract("Beat the ResNet-18 baseline on CIFAR-10 test accuracy", "cifar10-accuracy", "accuracy", "higher_is_better", 0.93)
HOUSING = contract("Lower RMSE on California housing on the fixed split", "california-housing", "rmse", "lower_is_better", 0.48)
ENERGY = contract("Hourly energy demand forecasting, 24h horizon", "uci-electricity", "mae", "lower_is_better", 0.15)
ARXIV = contract("Node classification on ogbn-arxiv", "ogbn-arxiv", "accuracy", "higher_is_better", 0.73)

IDEAS = [
    ("mixup-cutout-schedule", "Mixup and cutout on a cosine schedule"),
    ("snapshot-ensemble", "Snapshot ensemble of three checkpoints"),
    ("stochastic-depth-members", "Stochastic depth for ensemble members"),
]


def config_md(run_id: str, out: Path, contract_rel: str, metric: str, direction: str, threshold: float, goal: str) -> str:
    return f"""---
run_id: {run_id}
target_repository: {out}
contract_path: {contract_rel}
idea_batch: .ai-scientist/runs/{IDEATION_RUN}/ideas.json
primary_metric: {metric}
primary_metric_direction: {direction}
success_threshold: {threshold}
active_node_cap: 3
ranking_top_n: 2
python_env: uv run python
---

# Frozen Configuration

## Contract
{goal}

## Ideas
{chr(10).join(f"- `{i}`: {t}" for i, t in IDEAS)}
"""


def loop_state(run_id: str, phase_status: str, *, minutes_ago: float, state: dict, contract_rel: str, run_outcome=None, blocked_reason=None) -> dict:
    active = phase_status == "running"
    return {
        "schema_version": 1,
        "run_id": run_id,
        "active": active,
        "phase": "research",
        "phase_status": phase_status,
        "updated_at": ts(minutes_ago),
        "last_transition_id": f"tr-{run_id[:8]}-latest",
        "run_outcome": run_outcome,
        "blocked_reason": blocked_reason,
        "links": {
            "config": "config.md",
            "contract": contract_rel,
            "idea_batch": f".ai-scientist/runs/{IDEATION_RUN}/ideas.json",
            "discovery_notes": "discovery-notes.md",
            "learning_notes": "learning-notes.md",
        },
        "state": {"tasks": {}, "resources": {}, "resource_queue": {}, **state},
    }


def node(status: str, *, parent: str | None, title: str, idea_id: str, assignment: str, result_ref: str | None, minutes_ago: float, metrics: dict | None = None, evidence: str = "", next_action: str = "") -> dict:
    entry = {
        "status": status,
        "updated_at": ts(minutes_ago),
        "parent_node_id": parent,
        "title": title,
        "idea_id": idea_id,
        "assignment": assignment,
        "result_ref": result_ref,
        "evidence_summary": evidence,
        "next_action": next_action,
    }
    if metrics is not None:
        entry["metrics"] = metrics
    return entry


def work(node_id: str | None, status: str, result_ref: str, *, closed_at: str | None = None, **extra) -> dict:
    entry = {"status": status, "agent_thread_id": f"agent-{result_ref.split('/')[-2]}", "result_ref": result_ref, "node": node_id, **extra}
    if closed_at:
        entry["closed_at"] = closed_at
    return entry


def worker_report(node_id: str, title: str, status: str, metric: str, score: float | None, summary: str) -> str:
    score_line = f"| {metric} | {score} |" if score is not None else f"| {metric} | pending |"
    return f"""# {node_id}: {title}

**Status:** `{status}`

## Summary
{summary}

## Evidence
| metric | value |
|---|---|
{score_line}

## Todos
- [x] Materialize workspace and verify the frozen split
- [{'x' if score is not None else ' '}] Run the evaluator command on the official split
- [ ] Sweep two more seeds if the first result holds
"""


def journal(run_id: str, events: list[tuple[float, str, dict]]) -> str:
    lines = []
    for minutes_ago, event_type, fields in events:
        fields = dict(fields)
        rec = {"event_type": event_type, "timestamp": ts(minutes_ago), "run_id": run_id}
        for key in ("transition_id", "node_id", "subagent_id"):
            if key in fields:
                rec[key] = fields.pop(key)
        rec["details"] = fields
        lines.append(json.dumps(rec))
    lines.append("this line is not json and must be skipped")
    lines.append(json.dumps(["not", "an", "object"]))
    return "\n".join(lines) + "\n"


def checkpoint(minutes_ago: float, sections: list[str], note: str, node_id: str | None = None) -> tuple[float, str, dict]:
    fields = {"transition_id": f"tr-{int(minutes_ago * 10):06d}", "command": "research-loop-checkpoint", "changed_sections": sections, "note": note}
    if node_id:
        fields["node_id"] = node_id
    return (minutes_ago, "state_transition", fields)


def message(run_id: str, message_id: str, node_id: str, kind: str, prompt: str, *, created_minutes_ago: float,
            status: str = "pending", updated_minutes_ago: float | None = None, work_id: str | None = None,
            result_node_id: str | None = None, note: str | None = None) -> dict:
    """A `message-box/<id>.json` record (docs/SCHEMA.md 3.11)."""
    return {
        "id": message_id,
        "run_id": run_id,
        "node_id": node_id,
        "kind": kind,
        "prompt": prompt,
        "created_at": ts(created_minutes_ago),
        "status": status,
        "updated_at": ts(updated_minutes_ago if updated_minutes_ago is not None else created_minutes_ago),
        "work_id": work_id,
        "result_node_id": result_node_id,
        "note": note,
    }


def message_event(minutes_ago: float, msg: dict, command: str, status: str, **extra) -> tuple[float, str, dict]:
    """Journal line written by `message-box add` / `message-box update`."""
    fields = {"node_id": msg["node_id"], "command": command, "message_id": msg["id"], "status": status, **extra}
    if command == "message-box add":
        fields["kind"] = msg["kind"]
    return (minutes_ago, "message", fields)


# ---------------------------------------------------------------------------


def build_ideation(root: Path) -> None:
    run = root / "runs" / IDEATION_RUN
    write(run / "contract.json", CIFAR, at=ts(3000))
    write(
        run / "run.md",
        f"""# Run: {IDEATION_RUN}

- run_id: `{IDEATION_RUN}`
- status: `complete`
- phase: `ideation`

## Original request
Generate three pilot-backed ideas for beating ResNet-18 on CIFAR-10.

## Resume context
All three ideas passed the critic and each has a pilot report under `logs/pilots/`.
""",
        at=ts(2800),
    )
    write(
        run / "ideas.json",
        {
            "run_id": IDEATION_RUN,
            "ideas": [
                {"id": idea, "title": title, "idea_file": f"ideas/{idea}.md", "pilot_report": f"logs/pilots/{idea}/report.md"}
                for idea, title in IDEAS
            ],
        },
        at=ts(2810),
    )
    for n, (idea, title) in enumerate(IDEAS):
        write(run / "ideas" / f"{idea}.md", f"# {title}\n\n## Hypothesis\nA pilot on 10% of CIFAR-10 shows a positive trend for {idea}.\n", at=ts(2900 - n))
        write(run / "logs" / "pilots" / idea / "report.md", f"# Pilot: {title}\n\nPilot accuracy on the 10% subset: 0.8{n}.\n", at=ts(2850 - n))
    write(run / "logs" / "filter.md", "# Filtered candidates\n\n- contrastive-pretraining: rejected, uses test titles\n", at=ts(2830))
    write(run / "logs" / "data-insight" / "ideation" / "data_insight_ideation_report.md", "# Data insight\n\nClass balance is even; no leakage between train and test.\n", at=ts(2950))


def build_research(root: Path, out: Path) -> None:
    rid = RESEARCH_RUN
    run = root / "runs" / rid
    contract_rel = ".ai-scientist/contracts/cifar10-accuracy/research-contract.json"
    write(run / "config.md", config_md(rid, out, contract_rel, "accuracy", "higher_is_better", 0.93, CIFAR["goal"]), at=ts(300))

    # Node tree: N1 -> N2 -> N4, N1 -> N3, N5 root. Two live branches (N2/N4 and N5).
    nodes = {
        "N1": node("completed", parent=None, title="Mixup + cutout schedule", idea_id="mixup-cutout-schedule",
                   assignment="apply mixup and cutout on a cosine schedule to the ResNet-18 baseline",
                   result_ref="logs/workers/N1/N1-w-001/result.md", minutes_ago=120,
                   metrics={"accuracy": 0.931}, evidence="accuracy 0.931, +0.019 over baseline on the official split",
                   next_action="branch: ensemble on top"),
        "N2": node("running", parent="N1", title="Snapshot ensemble on N1", idea_id="snapshot-ensemble",
                   assignment="ensemble three snapshot checkpoints of the N1 recipe",
                   result_ref="logs/workers/N2/N2-w-001/result.md", minutes_ago=5,
                   metrics={"accuracy": 0.936}, evidence="first seed 0.936; second seed sweep running after revision",
                   next_action="read N2-w-002 result and decide on a third seed"),
        "N3": node("failed", parent="N1", title="Squeeze-excite variant", idea_id="mixup-cutout-schedule",
                   assignment="add squeeze-excite blocks to the N1 recipe",
                   result_ref="logs/workers/N3/N3-w-001/result.md", minutes_ago=60,
                   metrics={}, evidence="OOM at batch 512 twice; abandoned in favour of N2", next_action="none"),
        "N4": node("planned", parent="N2", title="Test-time augmentation on the ensemble", idea_id="snapshot-ensemble",
                   assignment="apply flip and crop TTA to the N2 ensemble", result_ref=None, minutes_ago=3,
                   evidence="", next_action="dispatch once N2 closes"),
        "N5": node("running", parent=None, title="Stochastic depth members", idea_id="stochastic-depth-members",
                   assignment="train ensemble members with stochastic depth",
                   result_ref="logs/workers/N5/N5-w-001/result.md", minutes_ago=8,
                   metrics={"accuracy": 0.930}, evidence="single seed 0.930, awaiting second seed", next_action="wait for N5-w-001"),
    }
    works = {
        "bl-001": work(None, "completed", "logs/baseline/bl-001/result.md", closed_at=ts(200)),
        "N1-w-001": work("N1", "completed", "logs/workers/N1/N1-w-001/result.md", closed_at=ts(120)),
        "N1-r-002": work("N1", "running", "logs/revisions/N1/N1-r-002/result.md", kind="revision", message_id=MSG_N1_ACK,
                         revision_plan_ref="logs/revisions/N1/N1-r-002/result.md", next_action="apply the user's warmup change"),
        "N2-w-001": work("N2", "completed", "logs/workers/N2/N2-w-001/result.md", closed_at=ts(40)),
        "N2-w-002": work("N2", "running", "logs/revisions/N2/N2-w-002/result.md", revision_plan_ref="logs/revisions/N2/N2-w-002/result.md", next_action="second seed"),
        "N3-w-001": work("N3", "failed", "logs/workers/N3/N3-w-001/result.md", closed_at=ts(60)),
        "N5-w-001": work("N5", "running", "logs/workers/N5/N5-w-001/result.md"),
        "rk-001": work(None, "completed", "logs/rankings/rk-001/result.md", closed_at=ts(30), ranking_id="rk-001",
                       cohort_node_ids=["N1", "N2", "N5"], top_n=2, selected_node_ids=["N2", "N5"]),
    }
    reports = {
        "logs/baseline/bl-001/result.md": ("Baseline", "# Baseline\n\nResNet-18 on the frozen split: accuracy 0.912.\n", ts(200)),
        "logs/workers/N1/N1-w-001/result.md": ("N1", worker_report("N1", "Mixup + cutout schedule", "completed", "accuracy", 0.931, "Mixup + cutout lifts accuracy by 0.019."), ts(120)),
        "logs/workers/N2/N2-w-001/result.md": ("N2", worker_report("N2", "Snapshot ensemble on N1", "completed", "accuracy", 0.936, "Three snapshots ensembled; one seed only."), ts(40)),
        "logs/revisions/N2/N2-w-002/result.md": ("N2", "# Revision plan for N2\n\nRun a second seed before ranking.\n", ts(20)),
        "logs/revisions/N1/N1-r-002/result.md": ("N1", "# Revision plan for N1\n\nUser message " + MSG_N1_ACK + ": extend the warmup to 5 epochs and re-run the N1 recipe.\n", ts(22)),
        "logs/workers/N3/N3-w-001/result.md": ("N3", worker_report("N3", "Squeeze-excite variant", "failed", "accuracy", None, "OOM at batch 512."), ts(60)),
        "logs/workers/N5/N5-w-001/result.md": ("N5", worker_report("N5", "Stochastic depth members", "running", "accuracy", 0.930, "First seed done."), ts(8)),
        "logs/rankings/rk-001/result.md": ("Ranking", "# Ranking rk-001\n\n1. N2\n2. N5\n3. N1\n", ts(30)),
    }
    for rel, (_, text, at) in reports.items():
        write(run / rel, text, at=at)

    state = {
        "orchestrator": {
            "next_action": "read N2-w-002 result, then dispatch N4 if N2 holds",
            "last_checkpoint_at": ts(3),
            "open_questions": {
                "q-seed-variance": {"statement": "Is the N2 gain larger than seed variance?", "status": "open"},
                "q-tta-cost": {"statement": "Does TTA fit the evaluator time budget?", "status": "answered"},
            },
        },
        "baseline": {"status": "completed", "result_ref": "logs/baseline/bl-001/result.md", "work_id": "bl-001"},
        "nodes": nodes,
        "work": works,
        "resources": {"leases": {"lease-1": {"work_id": "N2-w-002", "gpu": 0, "status": "running"}, "lease-2": {"work_id": "N5-w-001", "gpu": 1, "status": "running"}}},
        "resource_queue": {"pending": ["N4-w-001"], "released": ["N1-w-001", "N3-w-001"], "completed": ["bl-001"]},
        "selection": {"status": "pending", "selected_node": None},
    }
    write(run / "loop-state.json", loop_state(rid, "running", minutes_ago=3, state=state, contract_rel=contract_rel), at=ts(3))
    write(run / "baseline" / "baseline.json", {"status": "completed", "fixed_split_dir": "nodes/baseline/workspace/split", "split_manifest_ref": "nodes/baseline/workspace/split/manifest.json", "baseline_score_refs": ["logs/baseline/bl-001/result.md"]}, at=ts(200))
    write(run / "discovery-notes.md", "# Discovery notes\n\n- Mixup alone is worth +0.012; cutout adds +0.007.\n- Squeeze-excite does not fit in memory at batch 512.\n", at=ts(10))
    write(run / "learning-notes.md", "# Learning notes\n\n- Always sweep two seeds before ranking.\n", at=ts(12))
    write(run / "logs" / "agent-map.md", "# Agent map\n\n| work | agent |\n|---|---|\n| N2-w-002 | agent-N2-w-002 |\n", at=ts(20))
    write(run / "logs" / "resource-log.md", "# Resource log\n\n- lease-1 -> gpu 0\n- lease-2 -> gpu 1\n", at=ts(15))
    write(run / "nodes" / "N2" / "workspace" / "notes.txt", "scratch; the scanner never reads this\n", at=ts(5))

    # Message box: one open steer on N2, one being worked on N1, one turned down on N3.
    msg_n2 = message(rid, MSG_N2_PENDING, "N2", "branch", "Try the RandAugment policy from the AutoAugment paper as a child of N2.", created_minutes_ago=4)
    msg_n1 = message(rid, MSG_N1_ACK, "N1", "revision", "Extend the warmup to 5 epochs; the loss curve looks unstable in the first epoch.",
                     created_minutes_ago=30, status="acknowledged", updated_minutes_ago=22, work_id="N1-r-002")
    msg_n3 = message(rid, MSG_N3_REJECTED, "N3", "revision", "Retry squeeze-excite at batch 256.",
                     created_minutes_ago=50, status="rejected", updated_minutes_ago=45, note="N3 is failed and the OOM is a hardware limit; batch 256 halves throughput below the evaluator budget.")
    for msg in (msg_n2, msg_n1, msg_n3):
        write(run / "message-box" / f"{msg['id']}.json", msg, at=msg["updated_at"])
    write(run / "message-box" / "not-a-message.json", '{"id": 5, "status": "pending"', at=ts(1))

    write(run / "journal.jsonl", journal(rid, [
        (300, "setup", {"command": "research-loop-bootstrap", "contract": contract_rel}),
        checkpoint(250, ["baseline", "work"], "baseline dispatched"),
        checkpoint(200, ["baseline", "work"], "baseline completed"),
        checkpoint(190, ["nodes", "work"], "N1 dispatched", node_id="N1"),
        checkpoint(120, ["nodes", "work"], "N1 completed at 0.931", node_id="N1"),
        checkpoint(110, ["nodes", "work"], "N2 and N3 branched from N1", node_id="N2"),
        (100, "subagent_event", {"node_id": "N3", "subagent_id": "agent-N3-w-001", "event": "oom"}),
        checkpoint(60, ["nodes", "work"], "N3 failed", node_id="N3"),
        message_event(50, msg_n3, "message-box add", "pending"),
        message_event(45, msg_n3, "message-box update", "rejected", note=msg_n3["note"]),
        checkpoint(40, ["nodes", "work"], "N2-w-001 completed at 0.936", node_id="N2"),
        (35, "finding", {"node_id": "N2", "note": "gain may be within seed variance"}),
        message_event(30, msg_n1, "message-box add", "pending"),
        checkpoint(30, ["work"], "ranking rk-001 closed"),
        checkpoint(25, ["nodes", "work"], "N2 revision N2-w-002 dispatched", node_id="N2"),
        message_event(22, msg_n1, "message-box update", "acknowledged", work_id="N1-r-002"),
        checkpoint(22, ["work"], "N1 revision N1-r-002 dispatched for message " + MSG_N1_ACK, node_id="N1"),
        checkpoint(8, ["nodes", "work"], "N5 dispatched", node_id="N5"),
        message_event(4, msg_n2, "message-box add", "pending"),
        checkpoint(3, ["nodes", "orchestrator"], "N4 planned behind N2", node_id="N4"),
    ]), at=ts(3))


def build_success(root: Path, out: Path) -> None:
    rid = SUCCESS_RUN
    run = root / "runs" / rid
    contract_rel = ".ai-scientist/contracts/california-housing/research-contract.json"
    write(root / "contracts" / "california-housing" / "research-contract.json", {"research_contract": HOUSING}, at=ts(12000))
    write(run / "config.md", config_md(rid, out, contract_rel, "rmse", "lower_is_better", 0.48, HOUSING["goal"]), at=ts(11000))
    nodes = {
        "N1": node("completed", parent=None, title="GBM tuned", idea_id="mixup-cutout-schedule", assignment="tune the GBM baseline",
                   result_ref="logs/workers/N1/N1-w-001/result.md", minutes_ago=10500, metrics={"rmse": 0.497}, evidence="rmse 0.497"),
        "N2": node("accepted", parent="N1", title="GBM + target encoding", idea_id="snapshot-ensemble", assignment="add target encoding",
                   result_ref="logs/workers/N2/N2-w-001/result.md", minutes_ago=10100, metrics={"rmse": 0.471}, evidence="rmse 0.471, below threshold 0.48"),
        "N3": node("rejected", parent="N1", title="Leaky feature", idea_id="stochastic-depth-members", assignment="try neighbourhood price feature",
                   result_ref="logs/workers/N3/N3-w-001/result.md", minutes_ago=10200, metrics={"rmse": 0.402}, evidence="leakage: feature built from test rows"),
    }
    works = {
        "N1-w-001": work("N1", "completed", "logs/workers/N1/N1-w-001/result.md", closed_at=ts(10500)),
        "N2-w-001": work("N2", "accepted", "logs/workers/N2/N2-w-001/result.md", closed_at=ts(10100)),
        "N3-w-001": work("N3", "rejected", "logs/workers/N3/N3-w-001/result.md", closed_at=ts(10200)),
    }
    for nid, entry in nodes.items():
        write(run / entry["result_ref"], worker_report(nid, entry["title"], entry["status"], "rmse", entry["metrics"]["rmse"], entry["evidence_summary"]), at=entry["updated_at"])
    state = {
        "orchestrator": {"next_action": "none - run terminated with success", "last_checkpoint_at": ts(10000), "completion_audit": "completion-audit.md"},
        "baseline": {"status": "not_required"},
        "nodes": nodes,
        "work": works,
        "selection": {"status": "final", "selected_node": "N2", "outcome": "success", "result_ref": "selection.json"},
    }
    write(run / "loop-state.json", loop_state(rid, "success", minutes_ago=10000, state=state, contract_rel=contract_rel, run_outcome="success"), at=ts(10000))
    write(run / "selection.json", {"run_id": rid, "status": "final", "selected_node": "N2", "acceptance_rationale": "rmse 0.471 beats the 0.48 threshold on the fixed split with a clean leakage check",
                                   "result": {"rmse": 0.471}, "primary_metric": "rmse", "success_threshold": 0.48}, at=ts(10000))
    write(run / "completion-audit.md", "# Completion audit\n\nN2 accepted; N3 rejected for leakage.\n", at=ts(10000))
    write(run / "discovery-notes.md", "# Discovery notes\n\n- Target encoding is the whole gain.\n", at=ts(10050))
    write(run / "journal.jsonl", journal(rid, [
        (11000, "setup", {"command": "research-loop-bootstrap"}),
        checkpoint(10500, ["nodes", "work"], "N1 completed", node_id="N1"),
        checkpoint(10200, ["nodes", "work"], "N3 rejected for leakage", node_id="N3"),
        checkpoint(10100, ["nodes", "work"], "N2 accepted", node_id="N2"),
        (10000, "selection", {"selected_node": "N2"}),
        checkpoint(10000, ["selection", "orchestrator"], "terminal success"),
    ]), at=ts(10000))


def build_exhausted(root: Path, out: Path) -> None:
    rid = EXHAUSTED_RUN
    run = root / "runs" / rid
    contract_rel = ".ai-scientist/contracts/uci-electricity/research-contract.json"
    write(root / "contracts" / "uci-electricity" / "research-contract.json", {"research_contract": ENERGY}, at=ts(16000))
    write(run / "config.md", config_md(rid, out, contract_rel, "mae", "lower_is_better", 0.15, ENERGY["goal"]), at=ts(15900))
    nodes = {
        "N1": node("completed", parent=None, title="Seasonal naive + residual GBM", idea_id="mixup-cutout-schedule", assignment="residual boosting",
                   result_ref="logs/workers/N1/N1-w-001/result.md", minutes_ago=15500, metrics={"mae": 0.171}, evidence="mae 0.171, above threshold"),
        "N2": node("abandoned", parent="N1", title="Temporal fusion transformer", idea_id="snapshot-ensemble", assignment="TFT on the same split",
                   result_ref="logs/workers/N2/N2-w-001/result.md", minutes_ago=15100, metrics={"mae": 0.168}, evidence="mae 0.168; budget exhausted"),
    }
    works = {
        "N1-w-001": work("N1", "completed", "logs/workers/N1/N1-w-001/result.md", closed_at=ts(15500)),
        "N2-w-001": work("N2", "abandoned", "logs/workers/N2/N2-w-001/result.md", closed_at=ts(15100)),
    }
    for nid, entry in nodes.items():
        write(run / entry["result_ref"], worker_report(nid, entry["title"], entry["status"], "mae", entry["metrics"]["mae"], entry["evidence_summary"]), at=entry["updated_at"])
    state = {
        "orchestrator": {"next_action": "none - run terminated exhausted", "last_checkpoint_at": ts(15000)},
        "baseline": {"status": "completed", "result_ref": "logs/baseline/bl-001/result.md"},
        "nodes": nodes,
        "work": works,
        "selection": {"status": "final", "selected_node": None, "outcome": "exhausted"},
    }
    write(run / "loop-state.json", loop_state(rid, "exhausted", minutes_ago=15000, state=state, contract_rel=contract_rel, run_outcome="exhausted"), at=ts(15000))
    write(run / "discovery-notes.md", "# Discovery notes\n\n- Neither idea reaches 0.15 within budget.\n", at=ts(15000))
    write(run / "journal.jsonl", journal(rid, [
        (15900, "setup", {"command": "research-loop-bootstrap"}),
        checkpoint(15500, ["nodes", "work"], "N1 completed", node_id="N1"),
        checkpoint(15100, ["nodes", "work"], "N2 abandoned", node_id="N2"),
        checkpoint(15000, ["selection", "orchestrator"], "terminal exhausted"),
    ]), at=ts(15000))


def build_blocked(root: Path, out: Path) -> None:
    rid = BLOCKED_RUN
    run = root / "runs" / rid
    contract_rel = ".ai-scientist/contracts/ogbn-arxiv/research-contract.json"
    write(root / "contracts" / "ogbn-arxiv" / "research-contract.json", {"research_contract": ARXIV}, at=ts(2000))
    write(run / "config.md", config_md(rid, out, contract_rel, "accuracy", "higher_is_better", 0.73, ARXIV["goal"]), at=ts(1900))
    nodes = {
        "N1": node("completed", parent=None, title="GCN tuned", idea_id="mixup-cutout-schedule", assignment="tune the two-layer GCN",
                   result_ref="logs/workers/N1/N1-w-001/result.md", minutes_ago=1500, metrics={"accuracy": 0.712}, evidence="accuracy 0.712"),
        "N2": node("running", parent="N1", title="GraphSAGE with label propagation", idea_id="snapshot-ensemble", assignment="SAGE + LP",
                   result_ref="logs/workers/N2/N2-w-001/result.md", minutes_ago=1400, evidence="worker lost after machine reboot"),
    }
    works = {
        "N1-w-001": work("N1", "completed", "logs/workers/N1/N1-w-001/result.md", closed_at=ts(1500)),
        "N2-w-001": work("N2", "running", "logs/workers/N2/N2-w-001/result.md"),
    }
    write(run / "logs/workers/N1/N1-w-001/result.md", worker_report("N1", "GCN tuned", "completed", "accuracy", 0.712, "GCN tuned."), at=ts(1500))
    state = {
        "orchestrator": {"next_action": "user must restore the dataset mount, then resume N2-w-001", "last_checkpoint_at": ts(1300)},
        "baseline": {"status": "completed", "result_ref": "logs/baseline/bl-001/result.md"},
        "nodes": nodes,
        "work": works,
        "selection": {"status": "pending", "selected_node": None},
    }
    write(run / "loop-state.json", loop_state(rid, "blocked", minutes_ago=1300, state=state, contract_rel=contract_rel, run_outcome="blocked",
                                              blocked_reason="dataset mount /data/ogbn is missing; the evaluator cannot run"), at=ts(1300))
    write(run / "journal.jsonl", journal(rid, [
        (1900, "setup", {"command": "research-loop-bootstrap"}),
        checkpoint(1500, ["nodes", "work"], "N1 completed", node_id="N1"),
        checkpoint(1400, ["nodes", "work"], "N2 dispatched", node_id="N2"),
        checkpoint(1300, ["orchestrator"], "blocked: dataset mount missing"),
    ]), at=ts(1300))


def build(out: Path) -> None:
    root = out / ".ai-scientist"
    if root.exists():
        shutil.rmtree(root)

    write(root / "contracts" / "cifar10-accuracy" / "research-contract.json", {"research_contract": CIFAR}, at=ts(3100))
    write(root / "contracts" / "broken-draft" / "research-contract.json", '{"research_contract": "TODO: fill in",\n', at=ts(500))

    build_ideation(root)
    build_research(root, out)
    build_success(root, out)
    build_exhausted(root, out)
    build_blocked(root, out)
    write(root / "runs" / BROKEN_RUN / "loop-state.json", '{"run_id": "' + BROKEN_RUN + '", "phase": "research", "state": {', at=ts(1))

    write(root / "active-run.json", {"schema_version": 1, "run_id": RESEARCH_RUN, "phase": "research", "status": "active", "updated_at": ts(3), "target_repository": str(out)}, at=ts(3))
    print(f"wrote fixture to {root}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent)
    build(ap.parse_args().out.resolve())

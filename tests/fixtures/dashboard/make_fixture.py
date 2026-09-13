#!/usr/bin/env python3
"""Generate a dummy `.ai-scientist/` tree for exercising the dashboard UI.

Usage: python3 tests/fixtures/dashboard/make_fixture.py [--out DIR]
Then:  ai-scientist --target-repo tests/fixtures/dashboard dashboard --open
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc)


def ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n" if not isinstance(data, str) else data)


def contract(goal: str, dataset: str, metric: str, baseline: str, baseline_score: float, target: float) -> dict:
    return {
        "goal_type": "performance",
        "goal": goal,
        "dataset": {"name": dataset, "version": "1.0"},
        "split_protocol": "official train/test split, 10% of train held out for validation, seed 13",
        "allowed_inputs": ["train_inputs", "train_labels"],
        "forbidden_inputs": ["test_labels", "external_pretrained_weights"],
        "metrics": {"primary": metric, "secondary": ["loss", "wall_clock_sec"]},
        "baseline_reference": {"name": baseline, metric: baseline_score},
        "evaluator_command": "python eval.py --split test",
        "success_criteria": f"{metric} >= {target} on the official test split",
        "target_threshold": target,
        "non_drift_definition": "same dataset, split, evaluator and metric as this contract",
    }


CIFAR = contract("Beat the ResNet-18 baseline on CIFAR-10 test accuracy", "cifar-10", "accuracy", "resnet-18", 0.912, 0.93)
AGNEWS = contract("Improve macro-F1 on AG News topic classification", "ag-news", "macro_f1", "fasttext-bigram", 0.921, 0.94)
ARXIV = contract("Node classification on ogbn-arxiv", "ogbn-arxiv", "accuracy", "gcn-2layer", 0.702, 0.73)
HOUSING = contract("Lower RMSE on California housing, fixed split", "california-housing", "neg_rmse", "gbm-default", -0.512, -0.48)
ENERGY = contract("Hourly energy demand forecasting, 24h horizon", "uci-electricity", "neg_mae", "seasonal-naive", -0.184, -0.15)
CODESEARCH = contract("Code search retrieval on CodeSearchNet-python", "codesearchnet-python", "mrr", "bm25", 0.412, 0.5)


def loop_state(run_id: str, phase: str, status: str, *, active: bool, minutes_ago: float, state: dict, completed: list[str], **extra) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "active": active,
        "phase": phase,
        "phase_status": status,
        "started_at": ts(minutes_ago + 240),
        "updated_at": ts(minutes_ago),
        "completed_at": None if active else ts(minutes_ago),
        "run_outcome": None,
        "completion_audit": None,
        "completed_phases": {p: {"completed_at": ts(minutes_ago + 60)} for p in completed},
        "state": state,
        **extra,
    }


def node(node_id: str, status: str, metric: str, score: float | None, *, outcome: str | None = None, trials: int = 1, summary: str = "") -> dict:
    return {
        "node_id": node_id,
        "status": status,
        "benchmark_contract_version": "1",
        "metrics": {metric: score, "loss": round(1.2 - abs(score), 3), "wall_clock_sec": 1800 + trials * 600} if score is not None else {},
        "split_integrity": {"pass": status != "rejected", "summary": "official split verified"},
        "leakage_check": {"pass": status != "rejected", "summary": "no test samples in train set" if status != "rejected" else "test samples found in augmentation cache"},
        "result_summary": summary or f"{node_id}: {status}",
        "mode_deliverables": {},
        "outcome_type": outcome,
        "current_claim": summary,
        "trials": [{"trial_id": f"{node_id}-t{i}", "seed": 13 + i} for i in range(trials)],
    }


def journal(run_id: str, events: list[tuple[float, str, dict]]) -> str:
    lines = []
    for minutes_ago, event_type, details in events:
        rec = {"event_type": event_type, "timestamp": ts(minutes_ago), "run_id": run_id, "details": details}
        for key in ("node_id", "transition_id", "subagent_id"):
            if key in details:
                rec[key] = details.pop(key)
        lines.append(json.dumps(rec))
    return "\n".join(lines) + "\n"


def build(out: Path) -> None:
    root = out / ".ai-scientist"
    if root.exists():
        shutil.rmtree(root)

    # --- contracts ---------------------------------------------------------
    write(root / "contracts/cifar10-accuracy/research-contract.json", {"research_contract": CIFAR})
    write(root / "contracts/agnews-topic/research-contract.json", {"research_contract": AGNEWS})
    write(root / "contracts/broken-draft/research-contract.json", '{"research_contract": "TODO: fill in",\n')

    # --- run 1: ideation in progress ---------------------------------------
    rid = "20260913-ideation-agnews"
    write(root / f"runs/{rid}/config.json", {"run_id": rid, "target_repo": str(out), "research_contract": AGNEWS})
    write(root / f"runs/{rid}/ideas.json", [
        {"idea_id": f"idea-{i:02d}", "title": t, "status": s}
        for i, (t, s) in enumerate([
            ("Token dropout + cosine LR schedule", "accepted"),
            ("Label smoothing with class-balanced loss", "accepted"),
            ("Small distilled transformer encoder", "critic_pending"),
            ("Contrastive pretraining on unlabeled test titles", "rejected"),
            ("Snapshot ensemble of 3 checkpoints", "accepted"),
            ("Character n-gram side channel", "draft"),
        ], 1)
    ])
    write(root / f"runs/{rid}/loop-state.json", loop_state(rid, "ideation", "running", active=True, minutes_ago=4, completed=[], state={
        "orchestrator": {"next_action": "dispatch_critic", "iteration": 5, "next_action_details": {"idea_id": "idea-03"}},
        "ideas": {}, "subagents": {"critic-3": {"status": "running"}},
    }))
    write(root / f"runs/{rid}/journal.jsonl", journal(rid, [
        (180, "phase_start", {"phase": "ideation"}),
        (120, "subagent", {"subagent_id": "generator-1", "status": "completed", "ideas": 3}),
        (90, "subagent", {"subagent_id": "critic-1", "status": "completed", "verdict": "ACCEPT"}),
        (60, "subagent", {"subagent_id": "generator-2", "status": "completed", "ideas": 3}),
        (30, "subagent", {"subagent_id": "critic-2", "status": "completed", "verdict": "REJECT"}),
        (4, "subagent", {"subagent_id": "critic-3", "status": "running"}),
    ]))

    # --- run 2: research campaign, live (active-run) ------------------------
    rid = "20260912-research-cifar10"
    rrun = root / f"runs/{rid}"
    write(rrun / "config.json", {"run_id": rid, "target_repo": str(out), "research_contract": CIFAR, "research": {"active_node_cap": 3, "ranking_top_n": 2}})
    nodes = [
        ("node-001", "accepted", 0.931, "PROMISING_CONTINUE", 3, "Mixup + cutout schedule lifts accuracy +0.019 over baseline"),
        ("node-002", "running", 0.934, None, 2, "Label smoothing + cosine LR, second seed sweep running"),
        ("node-003", "failed", None, "INVALID", 1, "OOM during squeeze-excite training at batch 512"),
        ("node-004", "rejected", 0.951, "KILL", 1, "Leakage: test images in augmentation cache"),
        ("node-005", "pending", None, None, 0, "Snapshot ensemble, queued behind node-002"),
        ("node-006", "accepted", 0.928, "NEEDS_SCIENTIFIC_FRAMING", 4, "Ensemble beats baseline but mechanism unclear"),
    ]
    for nid, status, score, outcome, trials, summary in nodes:
        write(rrun / f"nodes/{nid}/node.json", node(nid, status, "accuracy", score, outcome=outcome, trials=trials, summary=summary))
    write(rrun / "loop-state.json", loop_state(rid, "research", "running", active=True, minutes_ago=1.5, completed=["ideation"], state={
        "orchestrator": {"next_action": "review_worker_result", "current_node": "node-002", "iteration": 14},
        "baseline_status": "provided_by_contract",
        "nodes": {nid: {"status": s} for nid, s, *_ in nodes},
        "work": {"work-node-002-t2": {"status": "running", "node_id": "node-002"}, "work-node-005-t0": {"status": "queued", "node_id": "node-005"}},
        "subagents": {"worker-node-002": {"status": "running"}},
        "resources": {"leases": {"lease-7": {"task_id": "work-node-002-t2", "status": "running", "gpus": 1}}},
        "selected_node": None,
    }))
    events = [(300, "phase_start", {"phase": "research"})]
    m = 280
    for nid, status, *_ in nodes:
        events.append((m, "node_created", {"node_id": nid, "seed_idea": f"idea-{nid[-1]}"}))
        m -= 8
        events.append((m, "subagent", {"subagent_id": f"worker-{nid}", "node_id": nid, "status": "completed" if status not in ("running", "pending") else status}))
        m -= 12
        if status in ("accepted", "rejected", "failed"):
            events.append((m, "critic", {"node_id": nid, "status": status, "verdict": {"accepted": "PROMISING_CONTINUE", "rejected": "KILL", "failed": "INVALID"}[status]}))
            m -= 10
    events += [
        (20, "resource", {"resource_id": "lease-7", "status": "acquired", "gpus": 1}),
        (6, "transition", {"transition_id": "t-14", "status": "running", "from": "dispatch_worker", "to": "review_worker_result"}),
        (1.5, "checkpoint", {"iteration": 14}),
    ]
    write(rrun / "journal.jsonl", journal(rid, events))
    write(root / "active-run.json", {"schema_version": 1, "run_id": rid, "phase": "research", "status": "active", "updated_at": ts(1.5), "target_repo": str(out)})

    # --- run 3: research blocked for manual recovery ------------------------
    rid = "20260911-research-ogbn-blocked"
    write(root / f"runs/{rid}/config.json", {"run_id": rid, "target_repo": str(out), "research_contract": ARXIV})
    for nid, status, score in [("node-001", "accepted", 0.712), ("node-002", "failed", None)]:
        write(root / f"runs/{rid}/nodes/{nid}/node.json", node(nid, status, "accuracy", score, trials=2))
    write(root / f"runs/{rid}/loop-state.json", loop_state(rid, "research", "blocked_manual_recovery", active=True, minutes_ago=95, completed=["ideation"], state={
        "orchestrator": {"next_action": "manual_recovery", "current_node": "node-002", "iteration": 6},
        "nodes": {"node-001": {"status": "accepted"}, "node-002": {"status": "failed"}},
        "selected_node": None,
    }, blocked_reason="journal hash mismatch at transition t-6: loop-state.json edited outside checkpoint"))
    write(root / f"runs/{rid}/journal.jsonl", journal(rid, [
        (400, "phase_start", {"phase": "research"}),
        (200, "critic", {"node_id": "node-001", "verdict": "PROMISING_CONTINUE"}),
        (95, "blocked", {"reason": "journal hash mismatch at transition t-6"}),
    ]))

    # --- run 4: review phase -------------------------------------------------
    rid = "20260910-review-housing"
    write(root / f"runs/{rid}/config.json", {"run_id": rid, "target_repo": str(out), "research_contract": HOUSING})
    for nid, status, score in [("node-001", "accepted", -0.497), ("node-002", "rejected", -0.521), ("node-003", "accepted", -0.471)]:
        write(root / f"runs/{rid}/nodes/{nid}/node.json", node(nid, status, "neg_rmse", score, trials=3))
    write(root / f"runs/{rid}/selection.json", {"schema_version": 1, "run_id": rid, "selection_status": "accepted", "provisional": False, "selected_node": "node-003",
                                                 "ranked_nodes": ["node-003", "node-001"], "manual_override": None, "rationale": "lowest RMSE with clean leakage check", "updated_at": ts(600)})
    write(root / f"runs/{rid}/loop-state.json", loop_state(rid, "review", "running", active=True, minutes_ago=35, completed=["ideation", "research"], state={
        "orchestrator": {"next_action": "structured_review", "iteration": 1},
        "selected_node": "node-003",
        "selection": {"selected_node": "node-003"},
    }))
    write(root / f"runs/{rid}/journal.jsonl", journal(rid, [
        (700, "phase_start", {"phase": "research"}),
        (600, "selection", {"selected_node": "node-003"}),
        (590, "validation", {"gate": "research_to_review", "exit_code": 0}),
        (580, "handoff", {"gate": "research_to_review", "approved": True}),
        (35, "phase_start", {"phase": "review"}),
    ]))

    # --- run 5: writeup complete ---------------------------------------------
    rid = "20260905-writeup-energy"
    write(root / f"runs/{rid}/config.json", {"run_id": rid, "target_repo": str(out), "research_contract": ENERGY})
    write(root / f"runs/{rid}/nodes/node-001/node.json", node("node-001", "accepted", "neg_mae", -0.141, outcome="ACCEPT_FINAL", trials=5, summary="Seasonal decomposition + gradient-boosted residuals"))
    write(root / f"runs/{rid}/selection.json", {"schema_version": 1, "run_id": rid, "selection_status": "accepted", "selected_node": "node-001", "ranked_nodes": ["node-001"], "updated_at": ts(5000)})
    write(root / f"runs/{rid}/loop-state.json", loop_state(rid, "writeup", "complete", active=False, minutes_ago=3000, completed=["ideation", "research", "review", "writeup"],
                                                          run_outcome="positive", state={"orchestrator": {"next_action": "done"}, "selected_node": "node-001"}))
    write(root / f"runs/{rid}/journal.jsonl", journal(rid, [
        (9000, "phase_start", {"phase": "ideation"}),
        (7000, "phase_start", {"phase": "research"}),
        (5000, "selection", {"selected_node": "node-001"}),
        (4000, "phase_start", {"phase": "review"}),
        (3500, "phase_start", {"phase": "writeup"}),
        (3010, "validation", {"gate": "launch", "exit_code": 0}),
        (3000, "handoff", {"gate": "launch", "approved": True}),
    ]))

    # --- run 6: cancelled ------------------------------------------------------
    rid = "20260901-research-codesearch-cancelled"
    write(root / f"runs/{rid}/config.json", {"run_id": rid, "target_repo": str(out), "research_contract": CODESEARCH})
    write(root / f"runs/{rid}/loop-state.json", loop_state(rid, "research", "cancelled", active=False, minutes_ago=15000, completed=["ideation"],
                                                          run_outcome="cancelled", state={"orchestrator": {"next_action": "cancelled"}}))
    write(root / f"runs/{rid}/journal.jsonl", journal(rid, [(15000, "cancelled", {"reason": "dataset license changed"})]))

    # --- run 7: half-written, no loop-state ------------------------------------
    write(root / "runs/20260913-bootstrap-partial/config.json", {"run_id": "20260913-bootstrap-partial"})

    print(f"wrote fixture to {root}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent)
    build(ap.parse_args().out.resolve())

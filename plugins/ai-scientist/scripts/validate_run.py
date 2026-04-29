#!/usr/bin/env python3
"""Fail-closed validator for Codex-native AI Scientist run artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ALLOWED_DEP_STATUSES = {"approved", "rejected", "not_needed"}
MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
GATE_DEST = {
    "ideation_to_research": ("ideation", "research"),
    "research_to_review": ("research", "review"),
    "review_to_writeup": ("review", "writeup"),
}

class ValidationError(Exception):
    pass

def load_json(path: Path) -> Any:
    if not path.exists():
        raise ValidationError(f"missing required JSON: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON {path}: {exc}") from exc

def load_first_json(paths: list[Path], label: str) -> Any:
    for path in paths:
        if path.exists():
            return load_json(path)
    raise ValidationError(f"missing required JSON: {label}")

def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValidationError(f"missing required JSONL: {path}")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid JSONL {path}:{index}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValidationError(f"JSONL record must be object: {path}:{index}")
        records.append(value)
    return records

def ai_root(target: Path) -> Path:
    target = target.resolve()
    candidate = target if target.name == ".ai-scientist" else target / ".ai-scientist"
    if not candidate.exists():
        raise ValidationError(f"missing .ai-scientist directory under {target}")
    return candidate

def pick_run(root: Path, run_id: str | None) -> Path:
    runs = root / "runs"
    if not runs.exists():
        raise ValidationError(f"missing runs directory: {runs}")
    if run_id:
        run = runs / run_id
        if not run.exists():
            raise ValidationError(f"missing requested run: {run}")
        return run
    candidates = sorted(p for p in runs.iterdir() if p.is_dir())
    if not candidates:
        raise ValidationError(f"no run directories under {runs}")
    return candidates[0]

def check_config(root: Path) -> dict[str, Any]:
    cfg = load_json(root / "config.json")
    if cfg.get("strictness_mode") not in MODES:
        raise ValidationError("config.json strictness_mode must be one of the five modes")
    if not cfg.get("target_repo"):
        raise ValidationError("config.json target_repo is required")
    budgets = cfg.get("api_budgets")
    if not isinstance(budgets, dict) or not budgets:
        raise ValidationError("config.json api_budgets must be a non-empty object")
    return cfg

def check_last_validation(run: Path, gate: str) -> dict[str, Any]:
    status = load_json(run / "run-status.json")
    mode = status.get("strictness_mode")
    if mode not in MODES:
        raise ValidationError("run-status.json strictness_mode must be one of the five modes")
    validations = status.get("last_validations")
    last = validations.get(gate) if isinstance(validations, dict) else None
    if not isinstance(last, dict):
        last = status.get("last_validation")
    if not isinstance(last, dict):
        raise ValidationError("run-status.json.last_validation is required")
    exit_code = last.get("exit_code", last.get("validator_exit_code"))
    if last.get("gate") != gate or exit_code != 0:
        raise ValidationError("run-status.json.last_validation is missing, stale, or non-zero")
    return status

def check_handoff(run: Path, gate: str) -> None:
    expected_from, expected_to = GATE_DEST[gate]
    for record in load_jsonl(run / "handoff.jsonl"):
        if record.get("gate") != gate:
            continue
        if record.get("from_phase") != expected_from or record.get("to_phase") != expected_to:
            continue
        if record.get("approved") is True and record.get("validator_exit_code") == 0 and record.get("approved_at"):
            return
    raise ValidationError(f"missing approved handoff.jsonl record for {gate} with validator_exit_code 0")

def check_ideation_to_research(root: Path, run: Path) -> None:
    check_config(root)
    ideas = load_json(root / "ideas" / "ideas.json")
    if not isinstance(ideas.get("ideas"), list) or not ideas["ideas"]:
        raise ValidationError("ideas/ideas.json must contain at least one idea")
    plan = load_json(run / "dependency-plan.json")
    deps = plan.get("planned_dependencies")
    if not isinstance(deps, list):
        raise ValidationError("dependency-plan.json planned_dependencies must be a list")
    for dep in deps:
        if not isinstance(dep, dict) or not dep.get("name"):
            raise ValidationError("each dependency entry needs a name")
        if dep.get("status") not in ALLOWED_DEP_STATUSES:
            raise ValidationError(f"dependency {dep.get('name')} missing approved/rejected/not_needed status")
    load_jsonl(run / "api-ledger.jsonl")
    check_last_validation(run, "ideation_to_research")
    check_handoff(run, "ideation_to_research")

def metric_score(metrics: dict[str, Any]) -> float:
    if "score" not in metrics:
        raise ValidationError("metrics must include numeric score")
    try:
        return float(metrics["score"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("metrics score must be numeric") from exc

def check_research_to_review(root: Path, run: Path) -> None:
    check_config(root)
    status = check_last_validation(run, "research_to_review")
    baseline = load_json(run / "baseline" / "metrics.json")
    baseline_score = metric_score(baseline)
    command_log = run / "baseline" / "command.log"
    if not command_log.exists() or not command_log.read_text().strip():
        raise ValidationError("baseline command.log is required")
    nodes_dir = run / "nodes"
    nodes = sorted(p for p in nodes_dir.glob("*") if p.is_dir()) if nodes_dir.exists() else []
    if not nodes:
        raise ValidationError("at least one experiment node is required")
    mode = status["strictness_mode"]
    best_score = None
    for node in nodes:
        if not (node / "command.log").exists() or not (node / "command.log").read_text().strip():
            raise ValidationError(f"node command.log is required: {node}")
        metrics = load_json(node / "metrics.json")
        score = metric_score(metrics)
        best_score = score if best_score is None else max(best_score, score)
        split = load_first_json(
            [node / "split_integrity.json", node / "split-integrity.json"],
            f"{node}/split_integrity.json or split-integrity.json",
        )
        if split.get("passed") is not True:
            raise ValidationError(f"split integrity evidence must pass: {node}")
        leakage = load_first_json(
            [node / "leakage_check.json", node / "leakage-check.json"],
            f"{node}/leakage_check.json or leakage-check.json",
        )
        if leakage.get("passed") is not True:
            raise ValidationError(f"leakage evidence must pass: {node}")
        load_first_json(
            [node / "result_summary.json", node / "result-summary.json"],
            f"{node}/result_summary.json or result-summary.json",
        )
        deliverables_path = node / "mode_deliverables.json"
        if deliverables_path.exists():
            deliverables = load_json(deliverables_path)
        else:
            deliverables = {mode: load_json(run / "mode-deliverables" / f"{mode}.json")}
        if mode not in deliverables or not deliverables.get(mode):
            raise ValidationError(f"mode-specific deliverables missing for {mode}: {node}")
    if best_score is None or best_score <= baseline_score:
        raise ValidationError("best node must beat baseline under declared benchmark")
    check_handoff(run, "research_to_review")

def check_review_to_writeup(root: Path, run: Path) -> None:
    check_config(root)
    status = check_last_validation(run, "review_to_writeup")
    review = load_json(run / "review" / "structured-review.json")
    verdict = review.get("verdict")
    verdict_obj = verdict if isinstance(verdict, dict) else {}
    for key in ["verdict", "leakage", "split_integrity", "baseline_comparison", "strictness_mode_criteria"]:
        if key not in review and key not in verdict_obj:
            raise ValidationError(f"structured review missing {key}")
    decision = verdict_obj.get("decision", verdict)
    if decision in {"reject", "rejected"} and not status.get("negative_or_blocked_writeup"):
        raise ValidationError("rejected runs must block writeup or be marked failed/negative")
    check_handoff(run, "review_to_writeup")

def check_launch(run: Path) -> None:
    decision = load_json(run / "verifier-decision.json")
    if decision.get("decision") != "go":
        raise ValidationError("verifier-decision.json decision must be go")
    blockers = decision.get("blockers")
    if blockers != []:
        raise ValidationError("verifier-decision.json blockers must be empty")

def check_principles(run: Path) -> None:
    data = load_json(run / "principles.json")
    principles = data.get("principles")
    if not isinstance(principles, list) or not principles:
        raise ValidationError("principles.json principles must be a non-empty list")
    for item in principles:
        gates = item.get("gates") if isinstance(item, dict) else None
        evidence = item.get("evidence_artifacts") if isinstance(item, dict) else None
        if not gates or not evidence:
            raise ValidationError("each principle must map to at least one gate and evidence artifact")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="target repo, fixture root, or .ai-scientist directory")
    parser.add_argument("--gate", choices=["ideation_to_research", "research_to_review", "review_to_writeup", "launch", "principles", "all"], default="all")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        root = ai_root(args.target)
        run = pick_run(root, args.run_id)
        if args.gate in {"ideation_to_research", "all"}:
            check_ideation_to_research(root, run)
        if args.gate in {"research_to_review", "all"}:
            check_research_to_review(root, run)
        if args.gate in {"review_to_writeup", "all"}:
            check_review_to_writeup(root, run)
        if args.gate in {"launch", "all"}:
            check_launch(run)
        if args.gate in {"principles", "all"}:
            check_principles(run)
    except ValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: {args.gate} validation succeeded for {run}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

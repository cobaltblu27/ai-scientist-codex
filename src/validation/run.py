#!/usr/bin/env python3
"""Fail-closed validator for Codex-native AI Scientist run artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.state import (
    evaluate_completion,
    open_resource_queue_ids,
)

MODES = {"scientist", "engineer", "custom"}
REQUIRED_CONTRACT_KEYS = {
    "goal_type",
    "primary_hypothesis",
    "dataset",
    "split_protocol",
    "allowed_inputs",
    "forbidden_inputs",
    "metrics",
    "metrics_that_matter",
    "non_negotiable_comparisons",
    "baseline_reference",
    "benchmark_plan",
    "evaluator_command",
    "success_criteria",
    "failure_criteria",
    "kill_criteria",
    "target_threshold",
    "non_drift_definition",
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

def check_config(root: Path, run: Path) -> dict[str, Any]:
    cfg_path = run / "config.json"
    cfg = load_json(cfg_path if cfg_path.exists() else root / "config.json")
    if cfg.get("strictness_mode") not in MODES:
        raise ValidationError("config.json strictness_mode must be scientist, engineer, or custom")
    if not cfg.get("target_repo"):
        raise ValidationError("config.json target_repo is required")
    if cfg.get("strictness_mode") == "custom" and not cfg.get("custom_criteria"):
        raise ValidationError("custom mode requires custom_criteria")
    return cfg

def check_loop_completion(root: Path, run: Path, expected_phase: str) -> None:
    result = evaluate_completion(root, run.name, expected_phase)
    if not result.complete:
        raise ValidationError(f"loop-state.json is not complete for {expected_phase}: {result.reason}")
    state = result.state or {}
    if state.get("phase") != expected_phase:
        raise ValidationError(f"loop-state.json phase must be {expected_phase}")

def check_research_contract(cfg: dict[str, Any]) -> None:
    contract = cfg.get("research_contract")
    if not isinstance(contract, dict) or not contract:
        raise ValidationError("research_contract is required")
    missing = sorted(REQUIRED_CONTRACT_KEYS - set(contract))
    if missing:
        raise ValidationError(f"research_contract missing fields: {', '.join(missing)}")


def check_research_loop_state(root: Path, run: Path) -> None:
    cfg = check_config(root, run)
    check_research_contract(cfg)
    campaign_mode = bool(cfg.get("campaign_mode"))
    if campaign_mode:
        idea_batch = cfg.get("idea_batch")
        if not isinstance(idea_batch, list) or not idea_batch:
            raise ValidationError("campaign research config requires non-empty idea_batch")
        if not isinstance(cfg.get("research_contract"), dict) or not cfg["research_contract"]:
            raise ValidationError("campaign research config requires research_contract")
    elif not isinstance(cfg.get("selected_idea_id"), str) or not cfg["selected_idea_id"].strip():
        raise ValidationError("config.json selected_idea_id is required for research")
    loop_state = load_json(run / "loop-state.json")
    if loop_state.get("phase") != "research":
        raise ValidationError("loop-state.json phase must be research")
    phase_state = loop_state.get("state")
    if not isinstance(phase_state, dict):
        raise ValidationError("loop-state.json state must be an object")
    if phase_state.get("mode") != cfg.get("strictness_mode"):
        raise ValidationError("loop-state.json mode must match config.json strictness_mode")
    if campaign_mode:
        if not isinstance(phase_state.get("idea_batch"), list) or not phase_state["idea_batch"]:
            raise ValidationError("campaign loop-state requires idea_batch")
        learning_notes = phase_state.get("learning_notes") if isinstance(phase_state.get("learning_notes"), dict) else {}
        notes_path = learning_notes.get("path") or cfg.get("learning_notes_ref")
        if not isinstance(notes_path, str) or not notes_path:
            raise ValidationError("campaign research requires learning_notes_ref")
    tasks = phase_state.get("tasks") if isinstance(phase_state.get("tasks"), dict) else {}
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            raise ValidationError(f"task state must be object: {task_id}")
        if task.get("status") not in {"completed", "cancelled", "failed", "abandoned", "accepted", "rejected"}:
            raise ValidationError(f"unresolved task blocks research_to_review: {task_id}:{task.get('status')}")
    resources = phase_state.get("resources") if isinstance(phase_state.get("resources"), dict) else {}
    leases = resources.get("leases") if isinstance(resources.get("leases"), dict) else {}
    active_leases = [
        str(lease_id)
        for lease_id, lease in leases.items()
        if not isinstance(lease, dict) or str(lease.get("status") or "acquired") in {"acquired", "running"}
    ]
    if active_leases:
        raise ValidationError(f"active resource leases block research_to_review: {', '.join(sorted(active_leases))}")
    open_queue = open_resource_queue_ids(phase_state)
    if open_queue:
        raise ValidationError(f"resource queue blocks research_to_review: {', '.join(open_queue)}")
    nodes = phase_state.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValidationError("loop-state.json must contain at least one node")
    selection_state = phase_state.get("selection")
    if not isinstance(selection_state, dict) or selection_state.get("status") != "final":
        raise ValidationError("loop-state.json selection must be final")
    selected_node = selection_state.get("selected_node") or phase_state.get("selected_node")
    if not isinstance(selected_node, str) or not selected_node:
        raise ValidationError("loop-state.json selected_node is required")
    if selected_node not in nodes:
        raise ValidationError("selected node is missing from loop-state nodes")
    selected = nodes[selected_node]
    if not isinstance(selected, dict):
        raise ValidationError("selected node state must be an object")
    if selected.get("status") != "accepted":
        raise ValidationError("selected node must be accepted")
    if (run / "selection.json").exists():
        selection = load_json(run / "selection.json")
        if selection.get("status") != "final" or selection.get("selected_node") != selected_node:
            raise ValidationError("selection.json must finalize the selected node")
    check_loop_completion(root, run, "research")


def check_research_to_review(root: Path, run: Path) -> None:
    check_research_loop_state(root, run)

def check_review_to_writeup(root: Path, run: Path) -> None:
    check_config(root, run)
    review = load_json(run / "review" / "structured-review.json")
    verdict = review.get("verdict")
    verdict_obj = verdict if isinstance(verdict, dict) else {}
    for key in ["verdict", "leakage", "split_integrity", "baseline_comparison", "strictness_mode_criteria"]:
        if key not in review and key not in verdict_obj:
            raise ValidationError(f"structured review missing {key}")
    decision = verdict_obj.get("decision", verdict)
    if decision in {"reject", "rejected"}:
        raise ValidationError("rejected review blocks positive writeup")

def check_writeup_artifacts(run: Path) -> None:
    manifest = load_json(run / "writeup" / "manifest.json")
    report_md = manifest.get("report_md")
    report_tex = manifest.get("report_tex")
    if not isinstance(report_md, str) or not report_md.strip():
        raise ValidationError("writeup manifest must include report_md")
    if not isinstance(report_tex, str) or not report_tex.strip():
        raise ValidationError("writeup manifest must include report_tex")
    md_path = run / report_md
    tex_path = run / report_tex
    if not md_path.exists():
        raise ValidationError(f"writeup markdown report is missing: {report_md}")
    if not tex_path.exists():
        raise ValidationError(f"writeup latex report is missing: {report_tex}")
    if manifest.get("disclosure_present") is not True:
        raise ValidationError("writeup manifest must confirm AI Scientist disclosure")
    if manifest.get("limitations_present") is not True:
        raise ValidationError("writeup manifest must confirm limitations")
    figures = manifest.get("figures")
    if not isinstance(figures, list) or not figures:
        raise ValidationError("writeup manifest must include at least one figure")
    md_text = md_path.read_text()
    tex_text = tex_path.read_text()
    for figure in figures:
        if not isinstance(figure, dict) or not isinstance(figure.get("path"), str):
            raise ValidationError("each writeup figure must include a path")
        figure_path = figure["path"]
        if not (run / figure_path).exists():
            raise ValidationError(f"writeup figure is missing: {figure_path}")
        if figure_path not in md_text and Path(figure_path).name not in tex_text:
            raise ValidationError(f"writeup report does not reference figure: {figure_path}")
    if manifest.get("require_pdf") is not False:
        report_pdf = manifest.get("report_pdf")
        if not isinstance(report_pdf, str) or not report_pdf.strip():
            raise ValidationError("writeup manifest must include report_pdf when require_pdf is true")
        if not (run / report_pdf).exists():
            raise ValidationError(f"writeup PDF report is missing: {report_pdf}")
    audit = load_json(run / "writeup" / "audit" / "final-audit.json")
    if audit.get("verdict") != "ACCEPT":
        raise ValidationError("writeup final audit verdict must be ACCEPT")


def check_launch(run: Path) -> None:
    check_writeup_artifacts(run)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="target repo, fixture root, or .ai-scientist directory")
    parser.add_argument("--gate", choices=["research_to_review", "review_to_writeup", "launch"], required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        root = ai_root(args.target)
        run = pick_run(root, args.run_id)
        if args.gate == "research_to_review":
            check_research_to_review(root, run)
        if args.gate == "review_to_writeup":
            check_review_to_writeup(root, run)
        if args.gate == "launch":
            check_launch(run)
    except ValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: {args.gate} validation succeeded for {run}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

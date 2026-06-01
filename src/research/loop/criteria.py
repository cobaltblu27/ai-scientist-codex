from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics import beats_baseline, comparison_symbol, metric_value, threshold_passes

MODE_REQUIREMENTS = {
    "scientist": {"reproducibility_note", "experiment_rationale", "split_leakage_evidence", "ablation_summary", "tuning_summary", "limitations"},
    "researcher": {"rationale", "reproducibility_note", "limitations", "sensitivity_evidence"},
    "balanced": {"rationale", "split_leakage_evidence", "result_summary"},
    "builder": {"runnable_artifact_summary", "metrics", "integration_notes", "known_risks"},
    "engineer": {"minimal_patch_summary", "metrics", "rollback_notes"},
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _passed(path: Path) -> bool:
    return path.exists() and load_json(path).get("passed") is True


def node_eligible(node_dir: Path, mode: str, metric_key: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for name in ["command.log", "metrics.json", "split_integrity.json", "leakage_check.json", "result_summary.json", "mode_deliverables.json", "runtime-mutation-check.json", "prompt.json", "node.json"]:
        if not (node_dir / name).exists():
            reasons.append(f"missing {name}")
    if (node_dir / "split_integrity.json").exists() and not _passed(node_dir / "split_integrity.json"):
        reasons.append("split integrity failed")
    if (node_dir / "leakage_check.json").exists() and not _passed(node_dir / "leakage_check.json"):
        reasons.append("leakage check failed")
    if (node_dir / "runtime-mutation-check.json").exists() and not _passed(node_dir / "runtime-mutation-check.json"):
        reasons.append("runtime mutation detected")
    if (node_dir / "metrics.json").exists():
        try:
            metric_value(load_json(node_dir / "metrics.json"), metric_key)
        except ValueError as exc:
            reasons.append(str(exc))
    if (node_dir / "mode_deliverables.json").exists():
        deliverables = load_json(node_dir / "mode_deliverables.json")
        supplied = set(deliverables.get(mode, [])) if isinstance(deliverables.get(mode), list) else set(deliverables.get(mode, {}).keys()) if isinstance(deliverables.get(mode), dict) else set()
        missing = MODE_REQUIREMENTS[mode] - supplied
        if missing:
            reasons.append(f"missing mode deliverables: {sorted(missing)}")
    return not reasons, reasons


def select_node(run_dir: Path, mode: str, metric_key: str, direction: str, threshold: float | None) -> dict[str, Any]:
    baseline_metrics = load_json(run_dir / "baseline" / "metrics.json")
    baseline = metric_value(baseline_metrics, metric_key)
    candidates = []
    for node in sorted((run_dir / "nodes").glob("*")) if (run_dir / "nodes").exists() else []:
        if not node.is_dir():
            continue
        eligible, reasons = node_eligible(node, mode, metric_key)
        if not eligible:
            candidates.append({"node_id": node.name, "eligible": False, "reasons": reasons})
            continue
        value = metric_value(load_json(node / "metrics.json"), metric_key)
        beats = beats_baseline(value, baseline, direction)
        threshold_ok = threshold_passes(value, threshold, direction)
        candidates.append({"node_id": node.name, "eligible": beats and threshold_ok, "metric": value, "beats_baseline": beats, "threshold_passed": threshold_ok, "reasons": [] if beats and threshold_ok else ["does not beat baseline or threshold"]})
    eligible_candidates = [c for c in candidates if c.get("eligible")]
    if direction == "maximize":
        selected = max(eligible_candidates, key=lambda c: c["metric"], default=None)
    else:
        selected = min(eligible_candidates, key=lambda c: c["metric"], default=None)
    return {
        "metric_key": metric_key,
        "metric_direction": direction,
        "comparison_operator": comparison_symbol(direction),
        "baseline_metric": baseline,
        "success_threshold": threshold,
        "selected_node": selected["node_id"] if selected else None,
        "selected_metric": selected["metric"] if selected else None,
        "threshold_passed": selected.get("threshold_passed") if selected else False,
        "threshold_satisfied": selected.get("threshold_passed") if selected else False,
        "candidates": candidates,
        "reason": "selected best eligible node" if selected else "no eligible node beat baseline under declared metric contract",
    }

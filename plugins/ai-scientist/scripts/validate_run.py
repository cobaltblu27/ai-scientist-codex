#!/usr/bin/env python3
"""Fail-closed validator for Codex-native AI Scientist run artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ALLOWED_DEP_STATUSES = {"approved", "rejected", "not_needed"}
ALLOWED_DEP_STATUS_DECISIONS = {"approved", "blocked", "rejected", "not_needed"}
MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
METRIC_DIRECTIONS = {"maximize", "minimize"}
GATE_DEST = {
    "ideation_to_research": ("ideation", "research"),
    "research_to_review": ("research", "review"),
    "review_to_writeup": ("review", "writeup"),
}

REQUIRED_MODE_DELIVERABLES = {
    "scientist": {"reproducibility_note", "experiment_rationale", "split_leakage_evidence", "ablation_summary", "tuning_summary", "limitations"},
    "researcher": {"rationale", "reproducibility_note", "limitations"},
    "balanced": {"rationale", "result_summary"},
    "builder": {"runnable_artifact_summary", "command_log", "metrics", "integration_notes", "known_risks"},
    "engineer": {"minimal_patch_summary", "command_log", "metrics", "rollback_notes"},
}

MODE_ALIASES = {
    "balanced": [{"split_leakage_evidence", "validation_evidence"}],
    "researcher": [{"ablation_summary", "sensitivity_evidence", "validation_evidence"}],
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

def validation_snapshot(record: dict[str, Any]) -> Any:
    return record.get("artifact_snapshot", record.get("artifact_hash", record.get("artifact_timestamp")))

def check_last_validation(run: Path, gate: str) -> tuple[dict[str, Any], dict[str, Any]]:
    status = load_json(run / "run-status.json")
    mode = status.get("strictness_mode")
    if mode not in MODES:
        raise ValidationError("run-status.json strictness_mode must be one of the five modes")
    validations = status.get("last_validations")
    last = validations.get(gate) if isinstance(validations, dict) else None
    location = f"run-status.json.last_validations.{gate}"
    if not isinstance(last, dict):
        last = status.get("last_validation")
        location = "run-status.json.last_validation"
    if not isinstance(last, dict):
        raise ValidationError(f"run-status.json.last_validations.{gate} or run-status.json.last_validation is required")
    exit_code = last.get("exit_code", last.get("validator_exit_code"))
    if last.get("gate") != gate or exit_code != 0:
        raise ValidationError(f"{location} is missing, stale, or non-zero for {gate}")
    return status, last

def check_handoff(run: Path, gate: str, expected_snapshot: Any | None = None) -> dict[str, Any]:
    expected_from, expected_to = GATE_DEST[gate]
    for record in reversed(load_jsonl(run / "handoff.jsonl")):
        if record.get("gate") != gate:
            continue
        if record.get("from_phase") != expected_from or record.get("to_phase") != expected_to:
            continue
        if record.get("approved") is True and record.get("validator_exit_code") == 0 and record.get("approved_at"):
            if expected_snapshot is not None and validation_snapshot(record) not in {None, expected_snapshot}:
                raise ValidationError(f"handoff.jsonl record for {gate} references a different validation snapshot")
            return record
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

def numeric_metric(metrics: dict[str, Any], metric_key: str, path_label: str) -> float:
    if metric_key not in metrics:
        raise ValidationError(f"{path_label} must include numeric metric_key {metric_key!r}")
    try:
        return float(metrics[metric_key])
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{path_label} metric {metric_key!r} must be numeric") from exc

def beats_baseline(candidate: float, baseline: float, direction: str) -> bool:
    if direction == "maximize":
        return candidate > baseline
    if direction == "minimize":
        return candidate < baseline
    raise ValidationError(f"metric_direction must be one of {sorted(METRIC_DIRECTIONS)}")

def threshold_satisfied(candidate: float, threshold: float, direction: str) -> bool:
    return candidate >= threshold if direction == "maximize" else candidate <= threshold

def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())

def artifact_snapshot(run: Path) -> str:
    """Hash stable research evidence while excluding validation/handoff decision files."""
    ignored = {"handoff.jsonl", "run-status.json", "journal.json", "evidence-validation-output.json", "final-validation-output.json", "verifier-decision.json"}
    h = hashlib.sha256()
    for path in sorted(run.rglob("*")):
        if not path.is_file():
            continue
        if path.name in ignored or "verifier-decisions" in path.parts:
            continue
        h.update(str(path.relative_to(run)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()

def check_dependency_status(run: Path) -> None:
    status_path = run / "dependency-status.json"
    if not status_path.exists():
        # Legacy ideation fixtures only have dependency-plan.json. Research-loop runs must add status.
        raise ValidationError("dependency-status.json is required for research governance")
    data = load_json(status_path)
    statuses = data.get("dependencies", data.get("planned_dependencies", data.get("statuses")))
    if not isinstance(statuses, list):
        raise ValidationError("dependency-status.json dependencies/planned_dependencies/statuses must be a list")
    for dep in statuses:
        if not isinstance(dep, dict) or not dep.get("name"):
            raise ValidationError("each dependency-status entry needs a name")
        decision = dep.get("decision", dep.get("status"))
        if decision not in ALLOWED_DEP_STATUS_DECISIONS:
            raise ValidationError(f"dependency-status entry {dep.get('name')} missing approved/blocked/rejected/not_needed decision")
        if decision == "blocked":
            raise ValidationError(f"dependency {dep.get('name')} is blocked")

def check_runtime_passed(path: Path, label: str) -> None:
    data = load_json(path)
    if data.get("passed") is not True:
        raise ValidationError(f"runtime mutation check must pass for {label}")
    unexpected = data.get("unexpected_mutations", data.get("unexpected_repo_mutations", data.get("changed_paths", [])))
    if unexpected:
        raise ValidationError(f"runtime mutation check found unexpected mutations for {label}")

def check_bool_passed(path: Path, label: str) -> None:
    data = load_json(path)
    if data.get("passed") is not True:
        raise ValidationError(f"{label} evidence must pass: {path}")

def selected_node_id(selection: dict[str, Any], status: dict[str, Any]) -> str:
    value = selection.get("selected_node", selection.get("selected_node_id", status.get("selected_node")))
    if not isinstance(value, str) or not value:
        raise ValidationError("selection.json selected_node is required")
    if status.get("selected_node") and status.get("selected_node") != value:
        raise ValidationError("run-status.json selected_node does not match selection.json")
    return value

def check_prompt_metadata(node: Path, node_id: str, mode: str) -> None:
    prompt = load_json(node / "prompt.json")
    if prompt.get("node_id") not in {node_id, None}:
        raise ValidationError(f"prompt.json node_id mismatch for {node_id}")
    action = prompt.get("action")
    if action not in {"draft", "debug", "improve", "tuning", "ablation"}:
        raise ValidationError(f"prompt.json action must be draft/debug/improve/tuning/ablation: {node}")
    if prompt.get("strictness_mode") != mode:
        raise ValidationError(f"prompt.json strictness_mode must match run mode {mode}: {node}")
    if not prompt.get("template_id"):
        raise ValidationError(f"prompt.json template_id is required: {node}")
    metadata = prompt.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValidationError(f"prompt.json metadata must be an object: {node}")
    # The prompt metadata contract is intentionally flexible for compatibility with
    # early fixtures: action, strictness mode, and template id are mandatory; metric
    # details may be recorded either in prompt metadata or in run-level research-plan.json.

def check_mode_deliverables(node: Path, mode: str) -> None:
    deliverables_path = node / "mode_deliverables.json"
    if deliverables_path.exists():
        deliverables = load_json(deliverables_path)
    else:
        deliverables = {mode: load_json(node.parent.parent / "mode-deliverables" / f"{mode}.json")}
    mode_data = deliverables.get(mode, deliverables)
    if not isinstance(mode_data, dict) or not mode_data:
        raise ValidationError(f"mode-specific deliverables missing for {mode}: {node}")
    missing = [key for key in REQUIRED_MODE_DELIVERABLES[mode] if key not in mode_data]
    for alias_group in MODE_ALIASES.get(mode, []):
        if not alias_group.intersection(mode_data):
            missing.append("/".join(sorted(alias_group)))
    # New research-loop runs must satisfy the named strictness-mode matrix.
    if missing:
        raise ValidationError(f"mode-specific deliverables for {mode} missing keys: {', '.join(sorted(set(missing)))}")

def check_selection_contract(selection: dict[str, Any], metric_key: str, direction: str, baseline_value: float, candidate_value: float) -> None:
    if selection.get("metric_key") != metric_key:
        raise ValidationError("selection.json metric_key must match research-plan.json")
    if selection.get("metric_direction") != direction:
        raise ValidationError("selection.json metric_direction must match research-plan.json")
    for key, expected in [("baseline_metric", baseline_value), ("selected_metric", candidate_value)]:
        if key in selection:
            try:
                actual = float(selection[key])
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"selection.json {key} must be numeric") from exc
            if actual != expected:
                raise ValidationError(f"selection.json {key} does not match metrics.json")
    comparator = selection.get("comparison_operator", selection.get("comparator", selection.get("comparison")))
    expected_comparator = ">" if direction == "maximize" else "<"
    if comparator is not None and comparator != expected_comparator:
        raise ValidationError("selection.json comparator does not match metric_direction")
    threshold = selection.get("success_threshold")
    if threshold is not None:
        threshold_value = float(threshold)
        expected = threshold_satisfied(candidate_value, threshold_value, direction)
        recorded = selection.get("threshold_satisfied", selection.get("threshold_result", selection.get("threshold_passed")))
        if isinstance(recorded, str):
            recorded = recorded.lower() in {"pass", "passed", "true", "satisfied"}
        if recorded is not None and bool(recorded) != expected:
            raise ValidationError("selection.json threshold result does not match metric_direction semantics")

def check_gate_specific_decision(run: Path, gate: str, expected_snapshot: Any | None) -> dict[str, Any]:
    decision = load_json(run / "verifier-decisions" / f"{gate}.json")
    if decision.get("decision") != "approved":
        raise ValidationError(f"verifier-decisions/{gate}.json decision must be approved")
    if decision.get("decision") in {"go", "no_go"}:
        raise ValidationError(f"verifier-decisions/{gate}.json must use approved/blocked/rejected, not launch go/no_go")
    if expected_snapshot is not None and validation_snapshot(decision) not in {None, expected_snapshot}:
        raise ValidationError(f"verifier-decisions/{gate}.json references a different validation snapshot")
    evidence = decision.get("evidence_validation", decision.get("validation"))
    if isinstance(evidence, dict):
        if evidence.get("exit_code", evidence.get("validator_exit_code")) not in {0, None}:
            raise ValidationError(f"verifier-decisions/{gate}.json evidence validation must have exit_code 0")
    return decision

def check_research_evidence(root: Path, run: Path) -> tuple[dict[str, Any], dict[str, Any], Any]:
    check_config(root)
    status = load_json(run / "run-status.json")
    mode = status.get("strictness_mode")
    if mode not in MODES:
        raise ValidationError("run-status.json strictness_mode must be one of the five modes")
    research_plan = load_json(run / "research-plan.json")
    metric_key = research_plan.get("metric_key")
    direction = research_plan.get("metric_direction")
    if not isinstance(metric_key, str) or not metric_key:
        raise ValidationError("research-plan.json metric_key is required")
    if direction not in METRIC_DIRECTIONS:
        raise ValidationError("research-plan.json metric_direction must be maximize or minimize")
    threshold = research_plan.get("success_threshold")

    load_json(run / "dependency-plan.json")
    check_dependency_status(run)
    load_jsonl(run / "api-ledger.jsonl")
    check_principles(run)
    if not (run / "dispatcher-events.jsonl").exists():
        raise ValidationError("dispatcher-events.jsonl is required")
    nodes_root = run / "nodes"
    all_nodes = sorted(p for p in nodes_root.glob("*") if p.is_dir()) if nodes_root.exists() else []
    if not all_nodes:
        raise ValidationError("at least one experiment node is required")
    selection = load_json(run / "selection.json")
    selected_id = selected_node_id(selection, status)

    baseline_dir = run / "baseline"
    baseline = load_json(baseline_dir / "metrics.json")
    baseline_value = numeric_metric(baseline, metric_key, "baseline/metrics.json")
    if not (baseline_dir / "command.log").exists() or not (baseline_dir / "command.log").read_text().strip():
        raise ValidationError("baseline command.log is required")
    check_bool_passed(load_first_path([baseline_dir / "split_integrity.json", baseline_dir / "split-integrity.json"], "baseline split integrity"), "baseline split integrity")
    check_bool_passed(load_first_path([baseline_dir / "leakage_check.json", baseline_dir / "leakage-check.json"], "baseline leakage"), "baseline leakage")
    check_runtime_passed(load_first_path([baseline_dir / "runtime-mutation-check.json", baseline_dir / "runtime_mutation_check.json"], "baseline runtime mutation check"), "baseline")

    node = run / "nodes" / selected_id
    if not node.is_dir():
        raise ValidationError(f"selected node does not exist: {node}")
    if not (node / "command.log").exists() or not (node / "command.log").read_text().strip():
        raise ValidationError(f"node command.log is required: {node}")
    metrics = load_json(node / "metrics.json")
    candidate_value = numeric_metric(metrics, metric_key, f"nodes/{selected_id}/metrics.json")
    if not beats_baseline(candidate_value, baseline_value, direction):
        raise ValidationError("selected node must beat baseline under declared metric_direction")
    if threshold is not None and not threshold_satisfied(candidate_value, float(threshold), direction):
        raise ValidationError("selected node does not satisfy success_threshold under declared metric_direction")
    check_selection_contract(selection, metric_key, direction, baseline_value, candidate_value)

    check_bool_passed(load_first_path([node / "split_integrity.json", node / "split-integrity.json"], f"{node}/split_integrity.json or split-integrity.json"), "split integrity")
    check_bool_passed(load_first_path([node / "leakage_check.json", node / "leakage-check.json"], f"{node}/leakage_check.json or leakage-check.json"), "leakage")
    load_first_json([node / "result_summary.json", node / "result-summary.json"], f"{node}/result_summary.json or result-summary.json")
    check_prompt_metadata(node, selected_id, mode)
    check_mode_deliverables(node, mode)
    check_runtime_passed(load_first_path([node / "runtime-mutation-check.json", node / "runtime_mutation_check.json"], f"{node}/runtime-mutation-check.json"), selected_id)
    load_first_json([node / "resource_usage.json", node / "resource-usage.json"], f"{node}/resource_usage.json or resource-usage.json")

    # Validate lineage artifacts when selection records them. The selected node itself was checked above.
    lineage = selection.get("lineage", [])
    if isinstance(lineage, list):
        for lineage_id in lineage:
            if lineage_id == selected_id:
                continue
            lineage_node = run / "nodes" / str(lineage_id)
            if lineage_node.is_dir():
                check_prompt_metadata(lineage_node, str(lineage_id), mode)
                check_runtime_passed(load_first_path([lineage_node / "runtime-mutation-check.json", lineage_node / "runtime_mutation_check.json"], f"{lineage_node}/runtime-mutation-check.json"), str(lineage_id))

    snapshot = selection.get("artifact_snapshot", status.get("artifact_snapshot", artifact_snapshot(run)))
    return status, {"metric_key": metric_key, "metric_direction": direction, "selected_node": selected_id}, snapshot

def load_first_path(paths: list[Path], label: str) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise ValidationError(f"missing required artifact: {label}")

def check_research_to_review(root: Path, run: Path, validation_mode: str) -> None:
    status, evidence_meta, snapshot = check_research_evidence(root, run)
    if validation_mode == "evidence":
        return
    _, last = check_last_validation(run, "research_to_review")
    if last.get("validation_mode") not in {None, "evidence", "final"}:
        raise ValidationError("research_to_review last validation has unknown validation_mode")
    for key, expected in evidence_meta.items():
        if key in last and last[key] != expected:
            raise ValidationError(f"research_to_review last validation {key} is stale")
    expected_snapshot = validation_snapshot(last) or snapshot
    check_handoff(run, "research_to_review", expected_snapshot)
    check_gate_specific_decision(run, "research_to_review", expected_snapshot)
    current_snapshot = artifact_snapshot(run)
    if is_sha256(expected_snapshot) and current_snapshot != expected_snapshot:
        raise ValidationError("research_to_review validation is stale: evidence artifacts changed after validation")

def check_review_to_writeup(root: Path, run: Path) -> None:
    check_config(root)
    status, _ = check_last_validation(run, "review_to_writeup")
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
    parser.add_argument("--validation-mode", choices=["evidence", "final"], default="final", help="research_to_review mode: evidence skips handoff/verifier-decision/last-validation circular checks; final enforces them")
    args = parser.parse_args()
    try:
        root = ai_root(args.target)
        run = pick_run(root, args.run_id)
        if args.gate in {"ideation_to_research", "all"}:
            check_ideation_to_research(root, run)
        if args.gate in {"research_to_review", "all"}:
            check_research_to_review(root, run, args.validation_mode)
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

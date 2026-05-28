#!/usr/bin/env python3
"""Fail-closed validator for Codex-native AI Scientist run artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from ai_scientist_state import evaluate_completion, journal_has_event, node_evidence_fingerprint, node_fresh_critic_reason, validate_node_contract

ALLOWED_DEP_STATUSES = {"approved", "rejected", "not_needed"}
MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
PAPER_MODES = {"scientist", "researcher"}
PRACTICAL_MODES = {"balanced", "builder", "engineer"}
PAPER_OUTCOME_TYPES = {"hypothesis_supported", "hypothesis_failed_with_evidence", "rescue_finding_with_failed_hypothesis"}
OUTCOME_TYPES = PAPER_OUTCOME_TYPES | {"practical_improvement"}
REQUIRED_CONTRACT_KEYS = {
    "primary_hypothesis",
    "success_criteria",
    "failure_criteria",
    "allowed_rescue_scope",
    "kill_criteria",
    "metrics_that_matter",
    "non_negotiable_comparisons",
}
DEFAULT_CRITIC_AGENT = {"model": "gpt-5.5", "reasoning_effort": "xhigh", "required": True}
REQUIRED_ACCEPTANCE_CHECKS = {
    "metric_contract_valid",
    "split_integrity_valid",
    "leakage_check_valid",
    "all_trials_accounted_for",
    "claim_matches_evidence",
    "mode_specific_bar_met",
}
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

def check_config(root: Path, run: Path) -> dict[str, Any]:
    cfg_path = run / "config.json"
    cfg = load_json(cfg_path if cfg_path.exists() else root / "config.json")
    if cfg.get("strictness_mode") not in MODES:
        raise ValidationError("config.json strictness_mode must be one of the five modes")
    if not cfg.get("target_repo"):
        raise ValidationError("config.json target_repo is required")
    budgets = cfg.get("api_budgets")
    if not isinstance(budgets, dict) or not budgets:
        raise ValidationError("config.json api_budgets must be a non-empty object")
    return cfg

def check_last_validation(run: Path, gate: str) -> dict[str, Any]:
    journal = run / "journal.jsonl"
    if journal.exists():
        for record in load_jsonl(journal):
            details = record.get("details") if isinstance(record.get("details"), dict) else {}
            exit_code = details.get("exit_code", details.get("validator_exit_code"))
            if record.get("event_type") == "validation" and details.get("gate") == gate and exit_code == 0:
                return {"strictness_mode": load_json(run / "config.json").get("strictness_mode", "scientist"), "last_validation": details}
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
    journal = run / "journal.jsonl"
    if journal.exists():
        for record in load_jsonl(journal):
            details = record.get("details") if isinstance(record.get("details"), dict) else {}
            exit_code = details.get("exit_code", details.get("validator_exit_code"))
            if record.get("event_type") == "handoff" and details.get("gate") == gate and details.get("approved") is True and exit_code == 0:
                return
    expected_from, expected_to = GATE_DEST[gate]
    for record in load_jsonl(run / "handoff.jsonl"):
        if record.get("gate") != gate:
            continue
        if record.get("from_phase") != expected_from or record.get("to_phase") != expected_to:
            continue
        if record.get("approved") is True and record.get("validator_exit_code") == 0 and record.get("approved_at"):
            return
    raise ValidationError(f"missing approved handoff journal record for {gate} with validator_exit_code 0")

def check_loop_completion(root: Path, run: Path, expected_phase: str) -> None:
    result = evaluate_completion(root, run.name, expected_phase)
    if not result.complete:
        raise ValidationError(f"loop-state.json is not complete for {expected_phase}: {result.reason}")
    state = result.state or {}
    if state.get("phase") != expected_phase:
        raise ValidationError(f"loop-state.json phase must be {expected_phase}")

def ideation_mode_preset(cfg: dict[str, Any]) -> dict[str, Any]:
    mode = cfg.get("strictness_mode")
    ideation = cfg.get("ideation") if isinstance(cfg.get("ideation"), dict) else {}
    modes = ideation.get("modes") if isinstance(ideation.get("modes"), dict) else {}
    preset = modes.get(mode)
    if not isinstance(preset, dict):
        raise ValidationError(f"config.json missing ideation mode preset: {mode}")
    return preset

def idea_is_researchable(idea: dict[str, Any], preset: dict[str, Any]) -> bool:
    evaluation = idea.get("evaluation")
    if evaluation == "ACCEPTED":
        return True
    if evaluation == "ACCEPTED_WITHOUT_REFERENCE":
        return bool(preset.get("allow_selection_without_reference"))
    return False


def artifact_snapshot(run: Path) -> str:
    ignored = {"handoff.jsonl", "run-status.json", "journal.json", "evidence-validation-output.json", "final-validation-output.json", "verifier-decision.json"}
    h = hashlib.sha256()
    for path in sorted(run.rglob("*")):
        if path.is_file() and path.name not in ignored and "verifier-decisions" not in path.parts:
            h.update(str(path.relative_to(run)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def check_ideation_to_research(root: Path, run: Path) -> None:
    cfg = check_config(root, run)
    preset = ideation_mode_preset(cfg)
    ideas = load_json(run / "ideas.json")
    if not isinstance(ideas.get("ideas"), list) or not ideas["ideas"]:
        raise ValidationError("runs/<run-id>/ideas.json must contain at least one idea")
    if load_json(run / "loop-state.json").get("phase_status") == "EXHAUSTED_NO_CANDIDATE":
        raise ValidationError("exhausted ideation has no researchable candidate")
    researchable = [
        idea for idea in ideas["ideas"]
        if isinstance(idea, dict) and idea_is_researchable(idea, preset)
    ]
    if not researchable:
        raise ValidationError("ideas.json must contain at least one researchable candidate for ideation_to_research")
    for idea in ideas["ideas"]:
        if not isinstance(idea, dict):
            raise ValidationError("ideas.json ideas must be objects")
        if idea.get("evaluation") == "ACCEPTED" and (not isinstance(idea.get("rank"), int) or idea["rank"] <= 0):
            raise ValidationError(f"ACCEPTED idea must include positive rank: {idea.get('id')}")
        if not isinstance(idea.get("score"), int):
            raise ValidationError(f"terminal idea must include integer score: {idea.get('id')}")
        if preset.get("s2_required") and idea.get("evaluation") == "ACCEPTED" and int(idea.get("literature_search_count") or 0) <= 0:
            raise ValidationError(f"ACCEPTED idea missing required literature evidence: {idea.get('id')}")
    if isinstance(cfg.get("dependency_plan"), dict):
        plan = cfg["dependency_plan"]
    else:
        plan = load_json(run / "dependency-plan.json")
    deps = plan.get("planned_dependencies")
    if not isinstance(deps, list):
        raise ValidationError("dependency-plan.json planned_dependencies must be a list")
    for dep in deps:
        if not isinstance(dep, dict) or not dep.get("name"):
            raise ValidationError("each dependency entry needs a name")
        if dep.get("status") not in ALLOWED_DEP_STATUSES:
            raise ValidationError(f"dependency {dep.get('name')} missing approved/rejected/not_needed status")
    journal = load_jsonl(run / "journal.jsonl")
    if preset.get("s2_required") and not any(record.get("event_type") == "api_call" for record in journal):
        raise ValidationError("journal.jsonl must contain at least one ideation api_call record")
    loop_state = load_json(run / "loop-state.json")
    phase_state = loop_state.get("state") if isinstance(loop_state.get("state"), dict) else {}
    ranking = phase_state.get("ranking") if isinstance(phase_state.get("ranking"), dict) else {}
    if ranking.get("status") != "final":
        raise ValidationError("loop-state.json ranking must be final")
    selected = ranking.get("selected_idea_id")
    if selected not in {idea.get("id") for idea in researchable}:
        raise ValidationError("selected_idea_id must refer to a researchable candidate")
    check_handoff(run, "ideation_to_research")
    check_loop_completion(root, run, "ideation")


def metric_score(metrics: dict[str, Any]) -> float:
    if "score" not in metrics:
        raise ValidationError("metrics must include numeric score")
    try:
        return float(metrics["score"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("metrics score must be numeric") from exc


def comparison_passes(selected_score: float, baseline_score: float, direction: str) -> bool:
    if direction == "minimize":
        return selected_score < baseline_score
    return selected_score > baseline_score


def improvement_margin(selected_score: float, baseline_score: float, direction: str) -> float:
    if direction == "minimize":
        return baseline_score - selected_score
    return selected_score - baseline_score


def critic_agent_config(cfg: dict[str, Any]) -> dict[str, Any]:
    configured = cfg.get("research") if isinstance(cfg.get("research"), dict) else {}
    configured = configured.get("critic_agent") if isinstance(configured.get("critic_agent"), dict) else {}
    merged = dict(DEFAULT_CRITIC_AGENT)
    merged.update({key: configured[key] for key in DEFAULT_CRITIC_AGENT if key in configured})
    return merged


def performance_bar_config(cfg: dict[str, Any]) -> dict[str, Any]:
    selection = cfg.get("selection") if isinstance(cfg.get("selection"), dict) else {}
    bar = selection.get("performance_bar") if isinstance(selection.get("performance_bar"), dict) else {}
    return {
        "min_improvement_margin": float(bar.get("min_improvement_margin", 0.0)),
        "min_confirmation_trials": int(bar.get("min_confirmation_trials", 1)),
    }


def required_critic_roles(mode: str) -> list[str]:
    if mode in PAPER_MODES:
        return ["evidence_auditor", "claim_critic"]
    return ["performance_auditor"]


def check_research_contract(cfg: dict[str, Any]) -> None:
    mode = cfg.get("strictness_mode")
    if mode not in PAPER_MODES:
        return
    contract = cfg.get("research_contract")
    if not isinstance(contract, dict) or not contract:
        raise ValidationError("research_contract is required for scientist/researcher")
    missing = sorted(key for key in REQUIRED_CONTRACT_KEYS if not contract.get(key))
    if missing:
        raise ValidationError(f"research_contract missing fields: {', '.join(missing)}")


def check_critic_accept_payload(critic: dict[str, Any], *, mode: str, role: str, node: dict[str, Any]) -> None:
    if critic.get("verdict") != "ACCEPT":
        raise ValidationError(f"required critic role did not ACCEPT: {role}")
    if critic.get("mode") != mode:
        raise ValidationError(f"critic mode mismatch for {role}")
    if critic.get("critic_role") != role:
        raise ValidationError(f"critic role mismatch for {role}")
    checks = critic.get("acceptance_checks")
    if not isinstance(checks, dict):
        raise ValidationError(f"critic acceptance_checks missing for {role}")
    for key in sorted(REQUIRED_ACCEPTANCE_CHECKS):
        if checks.get(key) is not True:
            raise ValidationError(f"critic {role} acceptance check failed: {key}")
    if checks.get("cheap_improvements_remaining") is not False:
        raise ValidationError(f"critic {role} reports cheap improvements remaining")
    scan = critic.get("missed_opportunity_scan")
    if not isinstance(scan, dict) or not isinstance(scan.get("searched"), list) or not scan["searched"]:
        raise ValidationError(f"critic {role} missed_opportunity_scan is incomplete")
    actionable = scan.get("actionable_improvements")
    if not isinstance(actionable, list):
        raise ValidationError(f"critic {role} actionable_improvements must be a list")
    if actionable:
        raise ValidationError(f"critic {role} accepted despite actionable improvements")
    if not isinstance(scan.get("why_remaining_ideas_are_not_worth_running"), str) or not scan["why_remaining_ideas_are_not_worth_running"].strip():
        raise ValidationError(f"critic {role} must justify why remaining ideas are not worth running")
    if mode in PAPER_MODES and role == "claim_critic":
        outcome = node.get("outcome_type")
        if outcome == "hypothesis_supported" and critic.get("contract_success_met") is not True:
            raise ValidationError("claim_critic must confirm contract success")
        if outcome == "hypothesis_failed_with_evidence" and (critic.get("contract_failure_met") is not True or critic.get("fundamental_failure") is not True):
            raise ValidationError("claim_critic must confirm fundamental contract failure")
        if outcome == "rescue_finding_with_failed_hypothesis" and (critic.get("contract_failure_met") is not True or critic.get("rescue_scope_met") is not True):
            raise ValidationError("claim_critic must confirm failed hypothesis and rescue scope")


def check_required_critic_roles(run: Path, cfg: dict[str, Any], node_id: str, node: dict[str, Any]) -> None:
    reviews = node.get("critic_reviews")
    if not isinstance(reviews, dict):
        raise ValidationError(f"accepted node missing critic_reviews: {node_id}")
    expected_fingerprint = node_evidence_fingerprint(node)
    runtime = critic_agent_config(cfg)
    mode = cfg["strictness_mode"]
    for role in required_critic_roles(mode):
        review = reviews.get(role)
        if not isinstance(review, dict):
            raise ValidationError(f"accepted node missing required critic role: {node_id}:{role}")
        if review.get("verdict") != "ACCEPT":
            raise ValidationError(f"accepted node critic role not accepted: {node_id}:{role}")
        if review.get("evidence_fingerprint") != expected_fingerprint:
            raise ValidationError(f"accepted node critic role stale: {node_id}:{role}")
        if review.get("spawn_model") != runtime["model"]:
            raise ValidationError(f"accepted node critic role wrong model: {node_id}:{role}")
        if review.get("spawn_reasoning_effort") != runtime["reasoning_effort"]:
            raise ValidationError(f"accepted node critic role wrong reasoning effort: {node_id}:{role}")
        critic_ref = review.get("critic_ref")
        if not isinstance(critic_ref, str) or not critic_ref:
            raise ValidationError(f"accepted node critic role missing ref: {node_id}:{role}")
        critic_path = Path(critic_ref)
        if not critic_path.exists():
            critic_path = run / critic_ref
        record = load_json(critic_path)
        spawn = record.get("spawn") if isinstance(record.get("spawn"), dict) else {}
        if spawn.get("spawn_model") != runtime["model"] or spawn.get("spawn_reasoning_effort") != runtime["reasoning_effort"]:
            raise ValidationError(f"critic log runtime mismatch: {node_id}:{role}")
        critic = record.get("critic") if isinstance(record.get("critic"), dict) else {}
        check_critic_accept_payload(critic, mode=mode, role=role, node=node)


def check_outcome_and_metric(
    cfg: dict[str, Any],
    node: dict[str, Any],
    *,
    selected_score: float,
    baseline_score: float,
    direction: str,
    selected_node: str,
) -> None:
    mode = cfg["strictness_mode"]
    outcome = node.get("outcome_type")
    if outcome not in OUTCOME_TYPES:
        raise ValidationError(f"accepted node missing valid outcome_type: {selected_node}")
    beats = comparison_passes(selected_score, baseline_score, direction)
    if mode in PAPER_MODES:
        check_research_contract(cfg)
        if outcome not in PAPER_OUTCOME_TYPES:
            raise ValidationError(f"paper mode cannot select outcome_type {outcome}")
        for key in ["current_claim", "claim_equivalence", "contract_evidence", "paper_worthiness"]:
            if not node.get(key):
                raise ValidationError(f"paper-mode accepted node missing {key}: {selected_node}")
        evidence = node.get("contract_evidence") if isinstance(node.get("contract_evidence"), dict) else {}
        if outcome == "hypothesis_supported":
            if not beats:
                raise ValidationError("hypothesis_supported selected node must beat baseline")
            if evidence.get("success_criteria_met") is not True:
                raise ValidationError("hypothesis_supported requires success_criteria_met")
        elif outcome == "hypothesis_failed_with_evidence":
            if evidence.get("failure_criteria_met") is not True or evidence.get("routine_optimization_failure") is True:
                raise ValidationError("hypothesis_failed_with_evidence requires fundamental failure evidence")
            if not node.get("fundamental_failure_reason"):
                raise ValidationError("hypothesis_failed_with_evidence requires fundamental_failure_reason")
        elif outcome == "rescue_finding_with_failed_hypothesis":
            if evidence.get("failure_criteria_met") is not True or evidence.get("rescue_scope_met") is not True:
                raise ValidationError("rescue finding requires failed hypothesis and rescue scope evidence")
    else:
        if not beats:
            raise ValidationError("selected node must beat baseline under declared benchmark")
        if mode in {"builder", "engineer"}:
            if outcome != "practical_improvement":
                raise ValidationError(f"{mode} selected node requires practical_improvement outcome")
            strong = node.get("strong_model_evidence") if isinstance(node.get("strong_model_evidence"), dict) else {}
            if strong.get("cheap_improvements_remaining") is not False:
                raise ValidationError(f"{mode} selected node has cheap improvements remaining")
            if strong.get("tuning_plateau_or_exhausted") is not True:
                raise ValidationError(f"{mode} selected node lacks tuning plateau/exhaustion evidence")
            bar = performance_bar_config(cfg)
            if improvement_margin(selected_score, baseline_score, direction) < bar["min_improvement_margin"]:
                raise ValidationError(f"{mode} selected node does not meet configured improvement margin")
            confirmations = strong.get("confirmation_trials")
            confirmation_count = len(confirmations) if isinstance(confirmations, list) else int(strong.get("confirmation_trial_count") or 0)
            if confirmation_count < bar["min_confirmation_trials"]:
                raise ValidationError(f"{mode} selected node lacks confirmation trials")


def check_research_file_artifacts(root: Path, run: Path) -> None:
    cfg = check_config(root, run)
    baseline = load_json(run / "baseline" / "metrics.json")
    baseline_score = metric_score(baseline)
    command_log = run / "baseline" / "command.log"
    if not command_log.exists() or not command_log.read_text().strip():
        raise ValidationError("baseline command.log is required")
    selection = load_json(run / "selection.json")
    selected_node = selection.get("selected_node")
    if not isinstance(selected_node, str) or not selected_node:
        raise ValidationError("selection.json selected_node is required")
    node_dir = run / "nodes" / selected_node
    node_json = load_json(node_dir / "node.json")
    if node_json.get("status") not in {"completed", "accepted"}:
        raise ValidationError(f"selected node is not completed/accepted: {selected_node}")
    metrics = load_json(node_dir / "metrics.json")
    selected_score = metric_score(metrics)
    metric_direction = selection.get("metric_direction") or load_json(run / "research-plan.json").get("metric_direction", "maximize")
    if metric_direction not in {"maximize", "minimize"}:
        raise ValidationError("metric_direction must be maximize or minimize")
    if not comparison_passes(selected_score, baseline_score, metric_direction):
        raise ValidationError("selected node must beat baseline under declared benchmark")
    for path in [
        run / "dependency-plan.json",
        run / "dependency-status.json",
        run / "api-ledger.jsonl",
        run / "principles.json",
        node_dir / "split_integrity.json",
        node_dir / "leakage_check.json",
        node_dir / "runtime-mutation-check.json",
        node_dir / "resource_usage.json",
    ]:
        if not path.exists():
            raise ValidationError(f"missing required research artifact: {path.relative_to(run)}")

def check_research_loop_state(root: Path, run: Path) -> None:
    cfg = check_config(root, run)
    loop_state = load_json(run / "loop-state.json")
    if loop_state.get("phase") != "research":
        raise ValidationError("loop-state.json phase must be research")
    phase_state = loop_state.get("state")
    if not isinstance(phase_state, dict):
        raise ValidationError("loop-state.json state must be an object")
    nodes = phase_state.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValidationError("loop-state.json must contain at least one node")
    selected_node = phase_state.get("selected_node")
    if not isinstance(selected_node, str) or not selected_node:
        raise ValidationError("loop-state.json selected_node is required")
    selection = load_json(run / "selection.json")
    if selection.get("selection_status") != "final" or selection.get("selected_node") != selected_node:
        raise ValidationError("selection.json must finalize the selected node")
    if selection.get("metric_direction") not in {"maximize", "minimize"}:
        raise ValidationError("selection.json metric_direction must be maximize or minimize")
    accepted_nodes = [node_id for node_id, node_state in nodes.items() if isinstance(node_state, dict) and node_state.get("status") == "accepted"]
    ranked_nodes = selection.get("ranked_nodes")
    if not isinstance(ranked_nodes, list):
        raise ValidationError("selection.json ranked_nodes must be a list")
    ranked_ids = {item.get("node_id") for item in ranked_nodes if isinstance(item, dict)}
    missing_ranked = sorted(set(accepted_nodes) - ranked_ids)
    if missing_ranked:
        raise ValidationError(f"selection.json missing accepted nodes: {', '.join(missing_ranked)}")
    baseline_score = metric_score(load_json(run / "baseline" / "metrics.json"))
    mode = cfg["strictness_mode"]
    selected_score = None
    for node_id, node_state in nodes.items():
        if not isinstance(node_state, dict):
            raise ValidationError(f"loop-state node must be object: {node_id}")
        status = node_state.get("status")
        node_json_path = run / "nodes" / node_id / "node.json"
        if status == "accepted":
            critic_reason = node_fresh_critic_reason(node_id, node_state, required_verdict="ACCEPT")
            if critic_reason:
                raise ValidationError(critic_reason)
            node_doc = load_json(node_json_path)
            critic_reason = node_fresh_critic_reason(node_id, node_doc, required_verdict="ACCEPT")
            if critic_reason:
                raise ValidationError(critic_reason)
            reason = validate_node_contract(node_id, node_doc, official_status="accepted")
            if reason:
                raise ValidationError(f"node.json invalid for {node_id}: {reason}")
            if node_doc.get("requires_worker_repair") is True:
                raise ValidationError(f"accepted node has unresolved repair: {node_id}")
            check_required_critic_roles(run, cfg, node_id, node_doc)
            metrics = node_doc.get("metrics")
            if isinstance(metrics, dict):
                score = metric_score(metrics)
                if node_id == selected_node:
                    selected_score = score
                    selected_node_doc = node_doc
            if mode in {"scientist", "researcher"}:
                novelty = node_doc.get("novelty")
                if not isinstance(novelty, dict) or novelty.get("pass") is not True:
                    raise ValidationError(f"novelty evidence must pass for {mode}: {node_id}")
        elif status in {"invalid", "rejected"}:
            expected_verdict = "INVALID" if status == "invalid" else "REJECT"
            critic_reason = node_fresh_critic_reason(node_id, node_state, required_verdict=expected_verdict)
            if critic_reason:
                raise ValidationError(critic_reason)
            node_doc = load_json(node_json_path)
            critic_reason = node_fresh_critic_reason(node_id, node_doc, required_verdict=expected_verdict)
            if critic_reason:
                raise ValidationError(critic_reason)
            if not (node_state.get("rejection_reason") or node_state.get("failure_signature")):
                raise ValidationError(f"rejected/invalid node missing reason: {node_id}")
        else:
            raise ValidationError(f"unresolved node state blocks research_to_review: {node_id}:{status}")
    if selected_score is None:
        raise ValidationError("selected node metrics.score is required")
    direction = selection["metric_direction"]
    selected_node_doc = locals().get("selected_node_doc")
    if not isinstance(selected_node_doc, dict):
        raise ValidationError("selected node document is required")
    check_outcome_and_metric(cfg, selected_node_doc, selected_score=selected_score, baseline_score=baseline_score, direction=direction, selected_node=selected_node)
    check_loop_completion(root, run, "research")


def check_research_final_verifier(run: Path) -> None:
    path = run / "verifier-decisions" / "research_to_review.json"
    if not path.exists():
        raise ValidationError("missing research_to_review verifier decision")
    decision = load_json(path)
    if decision.get("gate") != "research_to_review" or decision.get("decision") != "approved":
        raise ValidationError("research_to_review verifier decision must be approved")
    expected = decision.get("artifact_snapshot")
    current = artifact_snapshot(run)
    if expected != current:
        raise ValidationError("stale verifier decision: artifact snapshot changed after approval")


def check_research_to_review(root: Path, run: Path, validation_mode: str = "evidence") -> None:
    if (run / "loop-state.json").exists():
        check_research_loop_state(root, run)
    else:
        check_research_file_artifacts(root, run)
    if validation_mode == "final":
        check_handoff(run, "research_to_review")
        check_research_final_verifier(run)

def check_review_to_writeup(root: Path, run: Path) -> None:
    check_config(root, run)
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
    parser.add_argument("--validation-mode", choices=["evidence", "final"], default="evidence")
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

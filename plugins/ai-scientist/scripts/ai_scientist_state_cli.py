#!/usr/bin/env python3
"""Agent-facing helper CLI for AI Scientist research-loop state."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_scientist_state import (
    append_journal_event,
    audit_block_reason,
    block_for_manual_recovery,
    atomic_write_json,
    clear_active_run,
    config_path,
    data_hash,
    evaluate_loop_state_completion,
    has_stop_release_evidence,
    journal_has_event,
    journal_path,
    load_active_run,
    load_json_if_exists,
    load_loop_state,
    mutate_loop_state,
    node_evidence_fingerprint,
    node_fresh_critic_reason,
    node_dir,
    node_json_path,
    run_dir,
    selection_path,
    set_active_run,
    start_phase,
    utc_now,
    validate_active_run_contract,
)
from ideation_state import (
    IdeationStateError,
    cancel_ideation,
    cancel_intent,
    complete_ideation,
    complete_intent,
    codex_max_threads,
    current_config,
    cursor_for_state,
    exhaust_idea,
    exhaust_ideation,
    finalize_ready,
    finalize_idea,
    finalize_ranking,
    nested_value,
    rank_candidates,
    record_critic,
    record_draft,
    record_evidence_batch,
    record_semantic_scholar_search,
    reject_idea,
    resume_ideation,
    start_ideation,
    start_intent,
    start_intent_batch,
    start_revision,
    validate_max_subagents,
)
from writeup_state import (
    collect_figures as writeup_collect_figures,
    compile_pdf as writeup_compile_pdf,
    complete_audit as writeup_complete_audit,
    complete_writeup as writeup_complete_writeup,
    dependency_status as writeup_dependency_status,
    negative_complete as writeup_negative_complete,
    record_reports as writeup_record_reports,
    resume_writeup,
    start_audit as writeup_start_audit,
    start_writeup,
)
from usage_cap import (
    UsageCapError,
    is_snapshot_fresh,
    merge_usage_cap_config,
    read_codex_rate_limits,
    utc_now as usage_utc_now,
)

MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
PAPER_MODES = {"scientist", "researcher"}
PRACTICAL_MODES = {"balanced", "builder", "engineer"}
NODE_STATUSES = {"planning", "planned", "implementing", "running", "buggy", "repairing", "candidate", "validating", "accepted", "invalid", "rejected"}
NODE_TERMINAL_STATUSES = {"accepted", "invalid", "rejected"}
CRITIC_VERDICTS = {"ACCEPT", "REVISE", "INVALID", "REJECT"}
CRITIC_STATUS_BY_VERDICT = {"ACCEPT": "accepted", "REVISE": "repairing", "INVALID": "invalid", "REJECT": "rejected"}
CRITIC_ROLES = {"evidence_auditor", "claim_critic", "performance_auditor"}
DEFAULT_CRITIC_AGENT = {"model": "gpt-5.5", "reasoning_effort": "xhigh", "required": True}
REQUIRED_CONTRACT_KEYS = {
    "primary_hypothesis",
    "success_criteria",
    "failure_criteria",
    "allowed_rescue_scope",
    "kill_criteria",
    "metrics_that_matter",
    "non_negotiable_comparisons",
}
OUTCOME_TYPES = {
    "hypothesis_supported",
    "hypothesis_failed_with_evidence",
    "rescue_finding_with_failed_hypothesis",
    "practical_improvement",
}
PAPER_OUTCOME_TYPES = {
    "hypothesis_supported",
    "hypothesis_failed_with_evidence",
    "rescue_finding_with_failed_hypothesis",
}
REQUIRED_ACCEPTANCE_CHECKS = {
    "metric_contract_valid",
    "split_integrity_valid",
    "leakage_check_valid",
    "all_trials_accounted_for",
    "claim_matches_evidence",
    "mode_specific_bar_met",
}
DEFAULT_PERFORMANCE_BAR = {
    "min_improvement_margin": 0.0,
    "min_confirmation_trials": 1,
    "tuning_budget_policy": "plateau_or_exhausted",
    "cheap_improvement_definition": "bounded, low-risk change within the frozen run budget and resource policy",
}
SUBAGENT_STATUSES = {
    "planned",
    "running",
    "blocked_on_resource",
    "completed_unintegrated",
    "failed_unreviewed",
    "integrated",
    "rejected_with_reason",
    "abandoned_with_reason",
}
SUBAGENT_TERMINAL_STATUSES = {"integrated", "rejected_with_reason", "abandoned_with_reason"}
SUBAGENT_USAGE_GATED_STATUSES = {"planned", "running"}
NODE_USAGE_GATED_STATUSES = {"planning", "implementing", "running", "validating", "repairing"}
TARGET_VENUE_PRESETS = {"workshop", "domain_conference", "aaai_ijcai", "top_ml", "custom"}
TARGET_VENUE_BARS = {
    "workshop": (
        "Workshop bar: honest, reproducible, and useful. Incremental work is acceptable when the claim is clear, "
        "comparisons are fair, and limitations/negative evidence are disclosed."
    ),
    "domain_conference": (
        "Domain-conference bar: a credible field-specific contribution with clean evidence, a clear mechanism or practical insight, "
        "reasonable ablations, and enough novelty beyond routine tuning."
    ),
    "aaai_ijcai": (
        "AAAI/IJCAI bar: strong novelty or insight, clear mechanism, convincing ablations, rigorous comparisons, reproducibility, "
        "and low tolerance for incremental tuning or quiet claim drift."
    ),
    "top_ml": (
        "Top-ML bar: substantial method or scientific contribution, strong empirical support, broad and fair baselines, "
        "mechanistic understanding, robust ablations, and explicit controls against metric hacking."
    ),
    "custom": (
        "Custom venue bar: the user-provided venue name and notes are the hard threshold. If notes are vague, critics should ask "
        "for a better idea instead of accepting drift or performance-only hacks."
    ),
}
REVISION_VERDICTS = {"CONTINUE_NODE", "BRANCH", "STOP_DRIFTED", "STOP_EXHAUSTED"}
FINDING_KINDS = {"positive", "negative", "optimization", "bug", "drift", "exhaustion", "transferable"}

RESEARCH_NODE_CRITIC_PROMPTS = {
    "scientist": (
        "You are an independent research-node critic in scientist mode. Review node {node_id} for novelty, evidence, ablations, leakage/split integrity, "
        "reproducibility, publishability, and fidelity to the frozen research contract. Partial success, promising progress, quiet claim narrowing, "
        "or evidence needing validation must be REVISE/repairing, not ACCEPT."
    ),
    "researcher": (
        "You are an independent research-node critic in researcher mode. Review node {node_id} for research usefulness, evidence quality, ablations, leakage/split "
        "integrity, reproducibility, publishability, and fidelity to the frozen research contract. Partial success, promising progress, quiet claim narrowing, "
        "or evidence needing validation must be REVISE/repairing, not ACCEPT."
    ),
    "balanced": (
        "You are an independent research-node critic in balanced mode. Review node {node_id} for benchmark integrity, evidence, implementation quality, leakage/split "
        "integrity, reproducibility, practical value, risk, and whether cheap validation remains. Partial success, promising progress, or evidence needing validation "
        "must be REVISE/repairing, not ACCEPT."
    ),
    "engineer": (
        "You are an independent research-node critic in engineer mode. Review node {node_id} for benchmark integrity, implementation quality, performance, "
        "maintainability, reproducibility, risk, budget-backed tuning plateau, and missed high-expected-value improvements. Merely beating baseline is not enough. "
        "If a cheap bounded improvement remains, return REVISE/repairing, not ACCEPT."
    ),
    "builder": (
        "You are an independent research-node critic in builder mode. Review node {node_id} for benchmark integrity, implementation quality, performance, "
        "maintainability, reproducibility, buildability, risk, and remaining cheap reliability/integration improvements. Partial success, promising progress, "
        "or evidence needing validation must be REVISE/repairing, not ACCEPT."
    ),
}


class CliError(Exception):
    pass


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "json_file", None):
        value = json.loads(Path(args.json_file).read_text())
    elif getattr(args, "json", None):
        value = json.loads(args.json)
    else:
        value = {}
    if not isinstance(value, dict):
        raise CliError("payload must be a JSON object")
    return value


def load_payload_or_path(args: argparse.Namespace, default_path: Path | None = None) -> dict[str, Any]:
    if getattr(args, "json_file", None) or getattr(args, "json", None):
        return load_payload(args)
    if default_path is None:
        return {}
    if not default_path.exists() or not default_path.read_text().strip():
        return {}
    value = json.loads(default_path.read_text())
    if not isinstance(value, dict):
        raise CliError(f"payload at {default_path} must be a JSON object")
    return value


def research_pending_path(target: Path, run_id: str, kind: str, name: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in name).strip("-") or "payload"
    return run_dir(target, run_id) / "logs" / "pending" / kind / f"{safe_name}.json"


def ensure_pending_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


def strictness_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("strictness_mode") or "scientist")
    if mode not in MODES:
        raise CliError(f"invalid strictness mode: {mode}")
    return mode


def required_critic_roles(config: dict[str, Any]) -> list[str]:
    mode = strictness_mode(config)
    if mode in PAPER_MODES:
        return ["evidence_auditor", "claim_critic"]
    return ["performance_auditor"]


def default_critic_role(config: dict[str, Any], node: dict[str, Any]) -> str:
    reviews = node.get("critic_reviews") if isinstance(node.get("critic_reviews"), dict) else {}
    for role in required_critic_roles(config):
        review = reviews.get(role)
        if not isinstance(review, dict) or review.get("verdict") != "ACCEPT":
            return role
    return required_critic_roles(config)[-1]


def critic_agent_config(config: dict[str, Any]) -> dict[str, Any]:
    configured = nested_value(config, ["research", "critic_agent"])
    merged = dict(DEFAULT_CRITIC_AGENT)
    if isinstance(configured, dict):
        merged.update({key: configured[key] for key in DEFAULT_CRITIC_AGENT if key in configured})
    return merged


def performance_bar_config(config: dict[str, Any]) -> dict[str, Any]:
    configured = nested_value(config, ["selection", "performance_bar"])
    merged = dict(DEFAULT_PERFORMANCE_BAR)
    if isinstance(configured, dict):
        merged.update(configured)
    return merged


def research_contract(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("research_contract")
    return value if isinstance(value, dict) else {}


def research_contract_reason(config: dict[str, Any]) -> str | None:
    mode = strictness_mode(config)
    if mode not in PAPER_MODES:
        return None
    contract = research_contract(config)
    if not contract:
        return "research_contract_missing"
    missing = sorted(key for key in REQUIRED_CONTRACT_KEYS if not contract.get(key))
    if missing:
        return f"research_contract_missing_fields:{','.join(missing)}"
    return None


def default_research_contract(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("research_contract", "contract"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    idea = payload.get("selected_idea") or payload.get("idea")
    if isinstance(idea, dict) and idea.get("hypothesis"):
        hypothesis = str(idea["hypothesis"])
        metric = idea.get("expected_metric") or payload.get("metric_key") or "declared benchmark metric"
        return {
            "primary_hypothesis": hypothesis,
            "success_criteria": f"Evidence supports the hypothesis under the declared benchmark and {metric}.",
            "failure_criteria": f"Evidence shows the hypothesis is false or unsupported under the declared benchmark and {metric}.",
            "allowed_rescue_scope": "Allowed only when the original hypothesis verdict is explicitly failed and the narrower claim is disclosed.",
            "kill_criteria": "Stop or mark failed when required evidence cannot be produced without changing the frozen benchmark, split, or environment.",
            "metrics_that_matter": [metric],
            "non_negotiable_comparisons": ["baseline", "declared split", "leakage/split integrity checks"],
        }
    return None


def default_selection_config(payload: dict[str, Any]) -> dict[str, Any]:
    selection = dict(payload.get("selection") if isinstance(payload.get("selection"), dict) else {})
    selection.setdefault("good_enough_score_threshold", 75)
    performance_bar = dict(selection.get("performance_bar") if isinstance(selection.get("performance_bar"), dict) else {})
    for key, value in DEFAULT_PERFORMANCE_BAR.items():
        performance_bar.setdefault(key, value)
    selection["performance_bar"] = performance_bar
    return selection


def parse_token_budget_percent(value: Any) -> int:
    if value is None:
        raise CliError("research start requires --token-budget-percent")
    if isinstance(value, bool):
        raise CliError("--token-budget-percent must be an integer 1..100")
    try:
        budget = int(str(value))
    except (TypeError, ValueError) as exc:
        raise CliError("--token-budget-percent must be an integer 1..100") from exc
    if not 1 <= budget <= 100:
        raise CliError("--token-budget-percent must be between 1 and 100")
    return budget


def validate_research_start_fields(args: argparse.Namespace) -> tuple[str, str, int]:
    missing = []
    if not getattr(args, "strictness_mode", None):
        missing.append("--strictness-mode")
    if not getattr(args, "selected_idea_id", None):
        missing.append("--selected-idea-id")
    if not getattr(args, "target_venue_preset", None):
        missing.append("--target-venue-preset")
    if getattr(args, "token_budget_percent", None) is None:
        missing.append("--token-budget-percent")
    if missing:
        raise CliError("research start missing required fields: " + ", ".join(missing))
    mode = str(args.strictness_mode)
    if mode not in MODES:
        raise CliError(f"invalid strictness mode: {mode}")
    preset = str(args.target_venue_preset)
    if preset not in TARGET_VENUE_PRESETS:
        raise CliError("invalid target venue preset: " + preset)
    budget = parse_token_budget_percent(args.token_budget_percent)
    return mode, preset, budget


def freeze_target_venue(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    preset = str(args.target_venue_preset)
    name = str(args.target_venue_name or "").strip()
    notes = str(args.target_venue_notes or "").strip()
    payload_research = payload.get("research") if isinstance(payload.get("research"), dict) else {}
    payload_venue = payload_research.get("target_venue") if isinstance(payload_research.get("target_venue"), dict) else {}
    if not name and isinstance(payload_venue.get("name"), str):
        name = payload_venue["name"].strip()
    if not notes and isinstance(payload_venue.get("notes"), str):
        notes = payload_venue["notes"].strip()
    if preset == "custom" and not notes:
        raise CliError("--target-venue-notes is required when --target-venue-preset custom")
    return {
        "preset": preset,
        "name": name or preset,
        "notes": notes,
        "bar_summary": TARGET_VENUE_BARS[preset],
        "frozen": True,
        "source": "research start",
    }


def target_venue_config(config: dict[str, Any]) -> dict[str, Any]:
    research = config.get("research") if isinstance(config.get("research"), dict) else {}
    venue = research.get("target_venue") if isinstance(research.get("target_venue"), dict) else {}
    if not venue:
        return {"preset": "unspecified", "name": "unspecified", "notes": "", "bar_summary": "No target venue was frozen for this run."}
    return venue


def target_venue_summary(config: dict[str, Any]) -> str:
    venue = target_venue_config(config)
    summary = {
        "preset": venue.get("preset"),
        "name": venue.get("name"),
        "bar_summary": venue.get("bar_summary"),
        "notes": venue.get("notes"),
        "frozen": venue.get("frozen", True),
    }
    return json.dumps(summary, indent=2, sort_keys=True)


def selected_idea_id_from_config(config: dict[str, Any]) -> str | None:
    value = config.get("selected_idea_id") or nested_value(config, ["research", "selected_idea_id"])
    return str(value) if isinstance(value, str) and value.strip() else None


def role_guidance(role: str) -> str:
    if role == "evidence_auditor":
        return (
            "Role: evidence_auditor. Independently audit artifact truth: command refs, metric provenance, all trials, split/leakage consistency, "
            "stale or fabricated evidence, and cherry-picking. Do not judge based on prose if raw artifacts contradict it."
        )
    if role == "claim_critic":
        return (
            "Role: claim_critic. Judge whether the current claim resolves the frozen original hypothesis as supported, failed with evidence, "
            "or an approved rescue. Quiet claim narrowing is a false positive and must not be ACCEPT."
        )
    return (
        "Role: performance_auditor. Judge whether the model is genuinely strong for this mode. Search for missed high-value improvements. "
        "If a cheap bounded improvement remains within budget/resources, return REVISE even when the metric threshold is met."
    )


def rubric_snapshot(config: dict[str, Any], role: str) -> dict[str, Any]:
    mode = strictness_mode(config)
    return {
        "strictness_mode": mode,
        "critic_role": role,
        "required_roles": required_critic_roles(config),
        "required_acceptance_checks": sorted(REQUIRED_ACCEPTANCE_CHECKS),
        "cheap_improvements_must_be_false": True,
        "research_contract": research_contract(config),
        "performance_bar": performance_bar_config(config),
        "target_venue": target_venue_config(config),
        "selected_idea_id": selected_idea_id_from_config(config),
        "accepted_outcome_types": sorted(PAPER_OUTCOME_TYPES if mode in PAPER_MODES else OUTCOME_TYPES),
    }


def target_repo(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "target_repo", None) or Path.cwd()).resolve()


def active_run(target: Path, run_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
    if run_id:
        state = load_loop_state(target, run_id)
        if state:
            block_reason = audit_block_reason(target, run_id, state)
            if block_reason:
                if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                    block_for_manual_recovery(target, run_id, state, block_reason)
                raise CliError(block_reason)
        return run_id, state
    active = load_active_run(target)
    if not isinstance(active, dict) or not isinstance(active.get("run_id"), str):
        raise CliError("no active AI Scientist run; pass --run-id only for recovery/test paths")
    active_reason = validate_active_run_contract(active)
    if active_reason:
        raise CliError(f"active-run.json invalid: {active_reason}")
    rid = active["run_id"]
    state = load_loop_state(target, rid)
    if state:
        block_reason = audit_block_reason(target, rid, state)
        if block_reason:
            if str(state.get("phase_status") or "") != "blocked_manual_recovery":
                block_for_manual_recovery(target, rid, state, block_reason)
            raise CliError(block_reason)
    return rid, state


def response(status: str, **fields: Any) -> int:
    sys.stdout.write(json.dumps({"status": status, **fields}, indent=2, sort_keys=True) + "\n")
    return 0 if status == "ok" else 1


def resolve_research_max_subagents(target: Path, payload: dict[str, Any], explicit_max: int | None) -> tuple[int, str]:
    project_override = load_json_if_exists(target / ".ai-scientist" / "config.json")
    if not isinstance(project_override, dict):
        project_override = {}
    payload_max = nested_value(payload, ["research", "concurrency", "max_subagents"])
    project_max = nested_value(project_override, ["research", "concurrency", "max_subagents"])
    resolved = explicit_max
    source = "research start --max-subagents"
    if resolved is None:
        if payload_max is not None:
            resolved = payload_max
            source = "payload research.concurrency.max_subagents"
        elif project_max is not None:
            resolved = project_max
            source = "project .ai-scientist/config.json research.concurrency.max_subagents"
    if resolved is None:
        resolved = codex_max_threads(target)
        source = "codex [agents].max_threads"
    if resolved is None:
        resolved = 6
        source = "built-in default"
    return validate_max_subagents(resolved), source


def research_config(
    payload: dict[str, Any],
    max_subagents: int,
    source: str,
    *,
    no_limit_host_cap: bool = False,
    selected_idea_id: str | None = None,
    target_venue: dict[str, Any] | None = None,
    token_budget_percent: int | None = None,
) -> dict[str, Any]:
    research = dict(payload.get("research") if isinstance(payload.get("research"), dict) else {})
    critic_agent = dict(research.get("critic_agent") if isinstance(research.get("critic_agent"), dict) else {})
    for key, value in DEFAULT_CRITIC_AGENT.items():
        critic_agent.setdefault(key, value)
    research["critic_agent"] = critic_agent
    critic_gate = dict(research.get("critic_gate") if isinstance(research.get("critic_gate"), dict) else {})
    critic_gate.setdefault("paper_modes", {"required_roles": ["evidence_auditor", "claim_critic"]})
    critic_gate.setdefault("practical_modes", {"required_roles": ["performance_auditor"]})
    research["critic_gate"] = critic_gate
    concurrency = dict(research.get("concurrency") if isinstance(research.get("concurrency"), dict) else {})
    concurrency["max_subagents"] = max_subagents
    concurrency["source"] = source
    research["concurrency"] = concurrency
    if selected_idea_id is not None:
        research["selected_idea_id"] = selected_idea_id
    if target_venue is not None:
        research["target_venue"] = target_venue
    usage_cap = merge_usage_cap_config(research, no_limit_host_cap=no_limit_host_cap or None)
    if token_budget_percent is not None:
        usage_cap["cap_threshold_percent"] = float(token_budget_percent)
        usage_cap["block_new_work_at_percent"] = float(token_budget_percent)
        usage_cap["warning_threshold_percent"] = float(max(0, min(85, token_budget_percent - 10)))
        usage_cap["token_budget_percent"] = int(token_budget_percent)
        usage_cap["source"] = "research start --token-budget-percent"
    else:
        usage_cap.setdefault("block_new_work_at_percent", usage_cap.get("cap_threshold_percent"))
    research["usage_cap"] = usage_cap
    modes = dict(research.get("modes") if isinstance(research.get("modes"), dict) else {})
    for mode, template in RESEARCH_NODE_CRITIC_PROMPTS.items():
        preset = dict(modes.get(mode) if isinstance(modes.get(mode), dict) else {})
        preset.setdefault("node_critic_prompt_template", template)
        modes[mode] = preset
    research["modes"] = modes
    return research


def research_max_subagents(config: dict[str, Any]) -> int:
    value = nested_value(config, ["research", "concurrency", "max_subagents"])
    return validate_max_subagents(value if value is not None else 6)


def research_concurrency_details(config: dict[str, Any], phase_state: dict[str, Any]) -> dict[str, Any]:
    limit = research_max_subagents(config)
    source = nested_value(config, ["research", "concurrency", "source"]) or "unknown"
    subagents = phase_state.get("subagents") if isinstance(phase_state.get("subagents"), dict) else {}
    nonterminal = [
        subagent_id
        for subagent_id, subagent in subagents.items()
        if not isinstance(subagent, dict) or str(subagent.get("status") or "") not in SUBAGENT_TERMINAL_STATUSES
    ]
    available = max(0, limit - len(nonterminal))
    return {
        "subagent_concurrency_limit": limit,
        "subagent_concurrency_source": source,
        "nonterminal_subagent_count": len(nonterminal),
        "available_subagent_slots": available,
        "suggested_subagent_count": available,
    }


def usage_cap_config(config: dict[str, Any]) -> dict[str, Any]:
    research = config.get("research") if isinstance(config.get("research"), dict) else {}
    return merge_usage_cap_config(research)


def usage_cap_resets_at(snapshot: dict[str, Any]) -> str | None:
    values = []
    for key in ("primary", "secondary"):
        window = snapshot.get(key)
        if isinstance(window, dict) and isinstance(window.get("resetsAt"), str):
            values.append(window["resetsAt"])
    return sorted(values)[0] if values else None


def usage_cap_record(snapshot: dict[str, Any] | None, cfg: dict[str, Any], *, error: str | None = None, polled: bool = True) -> dict[str, Any]:
    effective = snapshot.get("effective_used_percent") if isinstance(snapshot, dict) else None
    warning = isinstance(effective, (int, float)) and effective >= cfg["warning_threshold_percent"]
    capped = isinstance(effective, (int, float)) and effective >= cfg["cap_threshold_percent"]
    if error:
        status = "error"
    elif not cfg["enabled"]:
        status = "disabled"
    elif capped:
        status = "capped"
    elif warning:
        status = "warning"
    else:
        status = "ok"
    record = {
        "enabled": cfg["enabled"],
        "source": cfg["source"],
        "limit_id": cfg["limit_id"],
        "warning_threshold_percent": cfg["warning_threshold_percent"],
        "cap_threshold_percent": cfg["cap_threshold_percent"],
        "block_new_work_at_percent": cfg.get("block_new_work_at_percent", cfg["cap_threshold_percent"]),
        "poll_interval_seconds": cfg["poll_interval_seconds"],
        "no_limit_host_cap": cfg["no_limit_host_cap"],
        "status": status,
        "warning": warning,
        "capped": capped,
        "polled": polled,
        "updated_at": usage_utc_now(),
    }
    if snapshot is not None:
        record["snapshot"] = snapshot
        record["effective_used_percent"] = effective
        record["resetsAt"] = usage_cap_resets_at(snapshot)
    if error:
        record["error"] = error
        record["warning"] = bool(cfg["no_limit_host_cap"])
    return record


def persist_usage_cap_state(target: Path, run_id: str, record: dict[str, Any], *, command: str) -> dict[str, Any]:
    def mutator(state: dict[str, Any]) -> None:
        state.setdefault("state", {})["usage_cap"] = record

    return mutate_loop_state(target, run_id, "state_transition", {"command": command, "usage_cap_status": record.get("status")}, mutator)


def refresh_usage_cap(target: Path, run_id: str, config: dict[str, Any], *, force: bool = False, command: str = "research usage-check") -> dict[str, Any]:
    cfg = usage_cap_config(config)
    state = load_loop_state(target, run_id)
    phase_state = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else {}
    existing = phase_state.get("usage_cap") if isinstance(phase_state.get("usage_cap"), dict) else None
    if not cfg["enabled"]:
        record = usage_cap_record(None, cfg, polled=False)
        persist_usage_cap_state(target, run_id, record, command=command)
        return record
    if not force and is_snapshot_fresh(existing, cfg["poll_interval_seconds"]):
        fresh = dict(existing)
        fresh["polled"] = False
        return fresh
    try:
        snapshot = read_codex_rate_limits(limit_id=cfg["limit_id"])
    except (UsageCapError, OSError) as exc:
        error_record = usage_cap_record(None, cfg, error=str(exc), polled=True)
        append_journal_event(target, run_id, "api_call", details={"command": command, "budget_key": "codex-rate-limit", "status": "error", "error": str(exc), "usage_cap": error_record})
        persist_usage_cap_state(target, run_id, error_record, command=command)
        if cfg["no_limit_host_cap"]:
            return error_record
        raise
    append_journal_event(target, run_id, "api_call", details={"command": command, "budget_key": "codex-rate-limit", "status": "ok", "usage_cap": snapshot})
    record = usage_cap_record(snapshot, cfg, polled=True)
    persist_usage_cap_state(target, run_id, record, command=command)
    return record


def selected_node_good_enough(target: Path, run_id: str, state: dict[str, Any], config: dict[str, Any]) -> bool:
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    selection = phase_state.get("selection") if isinstance(phase_state.get("selection"), dict) else {}
    selected = selection.get("selected_node") or phase_state.get("selected_node")
    if not isinstance(selected, str) or not selected:
        return False
    if selection.get("status") != "final":
        return False
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    if not isinstance(nodes.get(selected), dict) or nodes[selected].get("status") != "accepted":
        return False
    threshold = nested_value(config, ["selection", "good_enough_score_threshold"])
    threshold = float(threshold if threshold is not None else 75)
    persisted = load_json_if_exists(selection_path(target, run_id))
    ranked = persisted.get("ranked_nodes") if isinstance(persisted, dict) else None
    if not isinstance(ranked, list):
        ranked = []
    for item in ranked:
        if not isinstance(item, dict) or item.get("node_id") != selected:
            continue
        score = item.get("selection_score", item.get("score"))
        if isinstance(score, (int, float)) and float(score) >= threshold:
            return True
    return False


def block_on_usage_cap(target: Path, run_id: str, config: dict[str, Any], record: dict[str, Any], *, command: str) -> dict[str, Any]:
    state = load_loop_state(target, run_id)
    if not isinstance(state, dict):
        raise CliError(f"missing loop-state.json for run {run_id}")
    if selected_node_good_enough(target, run_id, state, config):
        return state
    reason = f"codex usage cap reached: {record.get('effective_used_percent')} >= {record.get('cap_threshold_percent')}"

    def mutator(new_state: dict[str, Any]) -> None:
        new_state["phase_status"] = "blocked_on_usage_limit"
        new_state["blocked_reason"] = reason
        phase_state = new_state.setdefault("state", {})
        phase_state["usage_cap"] = record
        phase_state["blocked_reason"] = reason
        orchestrator = phase_state.setdefault("orchestrator", {})
        if orchestrator.get("next_action") != "blocked_on_usage_limit":
            phase_state["usage_cap_blocked_next_action"] = {
                "next_action": orchestrator.get("next_action"),
                "next_action_details": orchestrator.get("next_action_details"),
            }
        orchestrator["next_action"] = "blocked_on_usage_limit"
        orchestrator["next_action_details"] = {"reason": reason, "usage_cap": record, "resetsAt": record.get("resetsAt")}
        orchestrator["last_checkpoint_at"] = utc_now()

    updated = mutate_loop_state(target, run_id, "state_transition", {"command": command, "blocked_reason": reason}, mutator)
    set_active_run(target, run_id, "research", "blocked_on_usage_limit")
    return updated


def unblock_usage_cap_if_recovered(target: Path, run_id: str, record: dict[str, Any]) -> None:
    state = load_loop_state(target, run_id)
    if not isinstance(state, dict) or state.get("phase_status") != "blocked_on_usage_limit" or record.get("capped"):
        return

    def mutator(new_state: dict[str, Any]) -> None:
        new_state["phase_status"] = "running"
        new_state["blocked_reason"] = None
        phase_state = new_state.setdefault("state", {})
        phase_state["usage_cap"] = record
        phase_state.pop("blocked_reason", None)
        previous = phase_state.pop("usage_cap_blocked_next_action", None)
        if isinstance(previous, dict):
            orchestrator = phase_state.setdefault("orchestrator", {})
            if isinstance(previous.get("next_action"), str) and previous["next_action"]:
                orchestrator["next_action"] = previous["next_action"]
            if isinstance(previous.get("next_action_details"), dict):
                orchestrator["next_action_details"] = previous["next_action_details"]

    mutate_loop_state(target, run_id, "state_transition", {"command": "research usage-cap recovered"}, mutator)
    set_active_run(target, run_id, "research", "active")


def ensure_usage_cap_allows_new_work(target: Path, run_id: str, *, command: str) -> dict[str, Any]:
    config = load_json_if_exists(config_path(target, run_id))
    if not isinstance(config, dict):
        raise CliError(f"missing config.json for run {run_id}")
    record = refresh_usage_cap(target, run_id, config, command=command)
    if record.get("capped") and not record.get("no_limit_host_cap"):
        block_on_usage_cap(target, run_id, config, record, command=command)
        raise CliError(f"blocked_on_usage_limit: resetsAt={record.get('resetsAt')}")
    return record


def default_config(
    target: Path,
    run_id: str,
    strictness_mode: str,
    payload: dict[str, Any],
    *,
    max_subagents: int | None = None,
    no_limit_host_cap: bool = False,
    selected_idea_id: str | None = None,
    target_venue: dict[str, Any] | None = None,
    token_budget_percent: int | None = None,
) -> dict[str, Any]:
    if strictness_mode not in MODES:
        raise CliError(f"invalid strictness mode: {strictness_mode}")
    resolved_max, concurrency_source = resolve_research_max_subagents(target, payload, max_subagents)
    contract = default_research_contract(payload)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "target_repo": str(target),
        "strictness_mode": strictness_mode,
        "selected_idea_id": selected_idea_id,
        "research": research_config(
            payload,
            resolved_max,
            concurrency_source,
            no_limit_host_cap=no_limit_host_cap,
            selected_idea_id=selected_idea_id,
            target_venue=target_venue,
            token_budget_percent=token_budget_percent,
        ),
        "api_budgets": payload.get("api_budgets", {"semantic_scholar": {"max_calls": 100}}),
        "workspace": payload.get("workspace", {"mode": "copy", "baseline_workspace": f".ai-scientist/runs/{run_id}/baseline-workspace"}),
        "dependency_plan": payload.get("dependency_plan", {"mode": "frozen", "planned_dependencies": []}),
        "benchmark_contract": payload.get("benchmark_contract", {"version": "v1", "command": payload.get("benchmark_command")}),
        "research_contract": contract or {},
        "resources": payload.get("resources", {"gpu": {"mode": "single_full_device_when_requested"}}),
        "selection": default_selection_config(payload),
        "created_at": utc_now(),
    }


def cmd_research_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    payload = load_payload(args)
    run_id = args.run_id
    mode, _preset, budget = validate_research_start_fields(args)
    selected_idea_id = str(args.selected_idea_id).strip()
    venue = freeze_target_venue(args, payload)
    cfg = default_config(
        target,
        run_id,
        mode,
        payload,
        max_subagents=args.max_subagents,
        no_limit_host_cap=args.no_limit_host_cap,
        selected_idea_id=selected_idea_id,
        target_venue=venue,
        token_budget_percent=budget,
    )
    concurrency = research_concurrency_details(cfg, {})
    initial_state = {
        "orchestrator": {
            "role": "main_codex_session",
            "iteration": 0,
            "next_action": "setup",
            "next_action_details": {"reason": "research run started", **concurrency},
            "last_checkpoint_at": utc_now(),
        },
        "workspace_plan_status": "pending",
        "dependency_plan_status": "pending",
        "baseline_status": "pending",
        "selected_idea_id": selected_idea_id,
        "target_venue": venue,
        "selected_node": None,
        "node_queue": [],
        "nodes": {},
        "subagents": {},
        "resources": {},
        "selection": {"status": "pending", "selected_node": None},
    }
    initial_state.update(payload.get("state", {}))
    state = start_phase(target, run_id, "research", initial_state)
    atomic_write_json(config_path(target, run_id), cfg)
    append_journal_event(target, run_id, "state_transition", details={"command": "research start", "state_hash": data_hash(state)})
    usage = refresh_usage_cap(target, run_id, cfg, force=True, command="research start usage-check")
    if usage.get("capped") and not usage.get("no_limit_host_cap"):
        block_on_usage_cap(target, run_id, cfg, usage, command="research start usage-cap block")
        raise CliError(f"blocked_on_usage_limit: resetsAt={usage.get('resetsAt')}")
    return response("ok", run_id=run_id, state_path=str(run_dir(target, run_id) / "loop-state.json"), config_path=str(config_path(target, run_id)), usage_cap=usage)


def cmd_research_resume(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.setdefault("state", {})
    orchestrator = phase_state.setdefault("orchestrator", {})
    next_action = orchestrator.get("next_action")
    if not next_action:
        raise CliError("active research is missing orchestrator.next_action")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    details = dict(orchestrator.get("next_action_details") if isinstance(orchestrator.get("next_action_details"), dict) else {})
    details.update(research_concurrency_details(cfg, phase_state))
    usage = refresh_usage_cap(target, run_id, cfg, command="research resume usage-check")
    unblock_usage_cap_if_recovered(target, run_id, usage)
    state = load_loop_state(target, run_id) or state
    phase_state = state.setdefault("state", {})
    orchestrator = phase_state.setdefault("orchestrator", {})
    next_action = orchestrator.get("next_action")
    details = dict(orchestrator.get("next_action_details") if isinstance(orchestrator.get("next_action_details"), dict) else {})
    details.update(research_concurrency_details(cfg, phase_state))
    details["usage_cap"] = usage
    if usage.get("capped") and not usage.get("no_limit_host_cap") and not selected_node_good_enough(target, run_id, load_loop_state(target, run_id) or state, cfg):
        block_on_usage_cap(target, run_id, cfg, usage, command="research resume usage-cap block")
        details["reason"] = "blocked on Codex usage cap"
        append_journal_event(target, run_id, "state_transition", details={"command": "research resume", "next_action": "blocked_on_usage_limit"})
        set_active_run(target, run_id, str(state.get("phase") or "research"), "blocked_on_usage_limit")
        return response("ok", run_id=run_id, next_action="blocked_on_usage_limit", next_action_details=details)
    append_journal_event(target, run_id, "state_transition", details={"command": "research resume", "next_action": next_action})
    set_active_run(target, run_id, str(state.get("phase") or "research"), "active")
    return response("ok", run_id=run_id, next_action=next_action, next_action_details=details)


def cmd_research_usage_check(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    usage = refresh_usage_cap(target, run_id, cfg, force=args.force, command="research usage-check")
    unblock_usage_cap_if_recovered(target, run_id, usage)
    return response("ok", run_id=run_id, usage_cap=usage)


def cmd_research_set_next_action(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)
    details = payload.get("details", {})
    if args.reason:
        details = {**details, "reason": args.reason}
    if not isinstance(details, dict) or not details.get("reason"):
        raise CliError("next_action details require a non-empty reason")

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        orchestrator = phase_state.setdefault("orchestrator", {})
        orchestrator["next_action"] = args.lane
        orchestrator["next_action_details"] = details
        orchestrator["last_checkpoint_at"] = utc_now()
        if args.node_id:
            orchestrator["current_node"] = args.node_id

    updated = mutate_loop_state(target, run_id, "state_transition", {"command": "research set-next-action", "lane": args.lane, "details": details}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, next_action=updated["state"]["orchestrator"]["next_action"])


def cmd_research_checkpoint(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        phase_state.update(payload.get("state", {}))
        orchestrator = phase_state.setdefault("orchestrator", {})
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "research checkpoint", "payload": payload}, mutator)
    return response("ok", run_id=run_id)


def cmd_research_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    audit = load_payload(args)
    if audit.get("passed") is not True:
        raise CliError("completion audit must include passed=true")
    simulated = deepcopy(state)
    simulated["active"] = False
    simulated["phase_status"] = "complete"
    simulated["completion_audit"] = audit
    result = evaluate_loop_state_completion(simulated)
    if not result.complete:
        raise CliError(f"research completion blocked: {result.reason}")

    def mutator(state: dict[str, Any]) -> None:
        state["active"] = False
        state["phase_status"] = "complete"
        state["completed_at"] = utc_now()
        state["completion_audit"] = audit

    mutate_loop_state(target, run_id, "state_transition", {"command": "research complete"}, mutator)
    set_active_run(target, run_id, "research", "validating")
    return response("ok", run_id=run_id, active_status="validating")


def cmd_research_cancel(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    def mutator(state: dict[str, Any]) -> None:
        state["active"] = False
        state["phase_status"] = "cancelled"
        state["run_outcome"] = "cancelled"
        state["cancellation_reason"] = args.reason
        state["completed_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "research cancel", "reason": args.reason}, mutator)
    clear_active_run(target, run_id)
    return response("ok", run_id=run_id, phase_status="cancelled")


def read_node(target: Path, run_id: str, node_id: str) -> dict[str, Any]:
    value = load_json_if_exists(node_json_path(target, run_id, node_id))
    return value if isinstance(value, dict) else {"node_id": node_id, "trials": []}


def write_node(target: Path, run_id: str, node_id: str, node: dict[str, Any]) -> None:
    node["node_id"] = node_id
    atomic_write_json(node_json_path(target, run_id, node_id), node)


def critic_log_path(target: Path, run_id: str, critic_id: str) -> Path:
    return run_dir(target, run_id) / "logs" / "critics" / f"{critic_id}.json"



def plan_log_path(target: Path, run_id: str, plan_id: str) -> Path:
    return run_dir(target, run_id) / "logs" / "plans" / f"{plan_id}.json"


def implementation_step_log_path(target: Path, run_id: str, step_id: str) -> Path:
    return run_dir(target, run_id) / "logs" / "implementation-steps" / f"{step_id}.json"




def revision_log_path(target: Path, run_id: str, revision_id: str) -> Path:
    return run_dir(target, run_id) / "logs" / "revisions" / f"{revision_id}.json"


def revision_critic_log_path(target: Path, run_id: str, critic_id: str) -> Path:
    return run_dir(target, run_id) / "logs" / "revision-critics" / f"{critic_id}.json"


def findings_jsonl_path(target: Path, run_id: str) -> Path:
    return run_dir(target, run_id) / "findings.jsonl"


def findings_md_path(target: Path, run_id: str) -> Path:
    return run_dir(target, run_id) / "findings.md"


def append_finding(target: Path, run_id: str, finding: dict[str, Any]) -> dict[str, Any]:
    kind = str(finding.get("kind") or "").strip()
    if kind not in FINDING_KINDS:
        raise CliError("finding kind must be one of " + ", ".join(sorted(FINDING_KINDS)))
    summary = str(finding.get("summary") or "").strip()
    if not summary:
        raise CliError("finding record requires non-empty summary")
    record = {
        "schema_version": 1,
        "finding_id": finding.get("finding_id") or f"finding-{uuid.uuid4().hex[:12]}",
        "run_id": run_id,
        "node_id": finding.get("node_id"),
        "kind": kind,
        "summary": summary,
        "source_ref": finding.get("source_ref"),
        "transferable": bool(finding.get("transferable", kind == "transferable")),
        "created_at": finding.get("created_at") or utc_now(),
    }
    for key in ("metrics", "details", "tags"):
        if key in finding:
            record[key] = finding[key]
    jsonl = findings_jsonl_path(target, run_id)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({key: value for key, value in record.items() if value is not None}, sort_keys=True) + "\n")
    md = findings_md_path(target, run_id)
    if not md.exists():
        md.write_text(f"# Findings for {run_id}\n\n", encoding="utf-8")
    node_text = f" node={record['node_id']}" if record.get("node_id") else ""
    source_text = f" source={record['source_ref']}" if record.get("source_ref") else ""
    with md.open("a", encoding="utf-8") as handle:
        handle.write(f"- {record['created_at']} [{kind}]{node_text}{source_text}: {summary}\n")
    append_journal_event(target, run_id, "finding", node_id=record.get("node_id"), details={"command": "finding record", "finding_id": record["finding_id"], "kind": kind})
    return record


def load_findings(target: Path, run_id: str, *, node_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    path = findings_jsonl_path(target, run_id)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if node_id and item.get("node_id") not in {node_id, None} and not item.get("transferable"):
            continue
        records.append(item)
    return records[-limit:]


def findings_context(target: Path, run_id: str, *, node_id: str | None = None, limit: int = 20) -> str:
    records = load_findings(target, run_id, node_id=node_id, limit=limit)
    if not records:
        return "[]"
    compact = [
        {
            "kind": item.get("kind"),
            "node_id": item.get("node_id"),
            "summary": item.get("summary"),
            "transferable": item.get("transferable"),
            "source_ref": item.get("source_ref"),
        }
        for item in records
    ]
    return json.dumps(compact, indent=2, sort_keys=True)


def record_payload_findings(target: Path, run_id: str, node_id: str | None, payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    records = []
    for item in findings:
        if not isinstance(item, dict):
            raise CliError("payload findings must be objects")
        record = dict(item)
        record.setdefault("node_id", node_id)
        record.setdefault("source_ref", source_ref)
        records.append(append_finding(target, run_id, record))
    return records


def node_has_lineage_stop(node: dict[str, Any]) -> bool:
    stop = node.get("lineage_stop")
    return isinstance(stop, dict) and stop.get("verdict") in {"STOP_DRIFTED", "STOP_EXHAUSTED"}

def next_sequence_id(phase_state: dict[str, Any], collection_name: str, prefix: str) -> str:
    collection = phase_state.get(collection_name) if isinstance(phase_state.get(collection_name), dict) else {}
    count = sum(1 for item_id in collection if str(item_id).startswith(prefix))
    return f"{prefix}{count + 1:03d}"


def build_node_architecture_plan_prompt(target: Path, run_id: str, node_id: str, plan_id: str, result_path: Path, payload: dict[str, Any], config: dict[str, Any]) -> str:
    objective = payload.get("objective") or payload.get("approach") or payload.get("summary") or "Plan this research node implementation."
    return (
        "You are planning one AI Scientist research node before implementation. Do not edit files yet.\n"
        "A node is one research direction. Create a scalable architecture plan that can be implemented incrementally.\n"
        "Do not compress the whole build into one oversized step. Split work into small verifiable steps, each with a done check.\n"
        "The frozen target venue bar is a hard threshold for novelty, mechanism, evidence, and drift control.\n"
        "If you discover a meaningfully different approach, list it under spawned_node_ideas instead of declaring the current node a fundamental failure.\n"
        "Underperforming or partial implementations are not evidence that the hypothesis failed; they are implementation state until the done definition is met.\n\n"
        f"Run id: {run_id}\nNode id: {node_id}\nPlan id: {plan_id}\nTarget repo: {target}\nObjective: {objective}\n"
        f"Selected idea id: {selected_idea_id_from_config(config)}\nResult path: {result_path}\n\n"
        "Frozen target venue bar:\n"
        + target_venue_summary(config)
        + "\n\nRelevant run findings to reuse or avoid:\n"
        + findings_context(target, run_id, node_id=node_id)
        + "\n\nWrite JSON only to result_path with this schema:\n"
        '{"node_id":"...","plan_id":"...","architecture_plan":{"objective":"...","venue_fit":"...","files_to_touch":["..."],'
        '"implementation_steps":[{"id":"step-001","title":"...","instructions":"...","done_check":"...","verification_commands":["..."]}],'
        '"same_node_optimization_plan":["hyperparameters/layers/debugging/ablations to try before revision"],'
        '"done_definition":["..."],"risks":["..."],"spawned_node_ideas":[{"title":"...","rationale":"..."}]}}\n'
    )


def build_node_step_prompt(target: Path, run_id: str, node_id: str, step_id: str, result_path: Path, plan: dict[str, Any], step: dict[str, Any], config: dict[str, Any]) -> str:
    return (
        "You are implementing one bounded step of one AI Scientist research node. Keep going until this step is actually done or a real blocker is hit.\n"
        "Do not cut corners to fit the session. If the overall node is not complete, report remaining work and recommended_status=implementing.\n"
        "Do not mark a half-built codebase as a failed hypothesis. A failed experiment is only scientific evidence after the implementation done definition and validation are met.\n"
        "Same-node work includes debugging, hyperparameter tuning, layer/model variants within the same mechanism, expected ablations, and sanity checks.\n"
        "If a useful finding emerges, include it in findings so later nodes can avoid failed fixes or reuse successful techniques.\n"
        "If a meaningfully different research direction emerges, add spawned_node_ideas; revision/branching is critic-gated and must stay above the frozen venue bar.\n\n"
        f"Run id: {run_id}\nNode id: {node_id}\nStep id: {step_id}\nTarget repo: {target}\nResult path: {result_path}\n\n"
        "Frozen target venue bar:\n"
        + target_venue_summary(config)
        + "\n\nRelevant run findings to reuse or avoid:\n"
        + findings_context(target, run_id, node_id=node_id)
        + "\n\nArchitecture plan:\n"
        + json.dumps(plan, indent=2, sort_keys=True)
        + "\n\nCurrent step:\n"
        + json.dumps(step, indent=2, sort_keys=True)
        + "\n\nWrite JSON only to result_path with this schema:\n"
        '{"node_id":"...","step_id":"...","step_complete":true,"done_definition_met":false,'
        '"files_changed":["..."],"commands_run":["..."],"remaining_work":["..."],'
        '"optimization_attempts":[{"change":"...","metric_before":0,"metric_after":0,"conclusion":"..."}],'
        '"findings":[{"kind":"positive|negative|optimization|bug|drift|exhaustion|transferable","summary":"...","transferable":false}],'
        '"spawned_node_ideas":[{"title":"...","rationale":"..."}],"recommended_status":"implementing|candidate",'
        '"node":{... optional complete candidate node evidence ...}}\n'
    )

def architecture_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = plan.get("implementation_steps")
    if not isinstance(steps, list) or not steps:
        raise CliError("architecture_plan.implementation_steps must be a non-empty list")
    normalized = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise CliError("each implementation step must be an object")
        title = step.get("title") or step.get("name") or f"step-{index:03d}"
        instructions = step.get("instructions") or step.get("description")
        done_check = step.get("done_check") or step.get("done")
        if not isinstance(title, str) or not title.strip():
            raise CliError("each implementation step requires title")
        if not isinstance(instructions, str) or not instructions.strip():
            raise CliError("each implementation step requires instructions")
        if not isinstance(done_check, str) or not done_check.strip():
            raise CliError("each implementation step requires done_check")
        normalized.append({**step, "id": step.get("id") or f"step-{index:03d}", "title": title, "instructions": instructions, "done_check": done_check})
    return normalized

def repair_log_path(target: Path, run_id: str, repair_id: str) -> Path:
    return run_dir(target, run_id) / "logs" / "repairs" / f"{repair_id}.json"


def validate_critic_spawn(pending: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    required = pending.get("required_runtime") if isinstance(pending.get("required_runtime"), dict) else critic_agent_config(config)
    if required.get("required") is not True:
        return {}
    spawn = pending.get("spawn") if isinstance(pending.get("spawn"), dict) else None
    if not spawn:
        raise CliError("critic spawn metadata is required before critic-complete")
    if spawn.get("spawn_model") != required.get("model"):
        raise CliError(f"critic spawn model mismatch: expected {required.get('model')}, found {spawn.get('spawn_model')}")
    if spawn.get("spawn_reasoning_effort") != required.get("reasoning_effort"):
        raise CliError(f"critic spawn reasoning effort mismatch: expected {required.get('reasoning_effort')}, found {spawn.get('spawn_reasoning_effort')}")
    return spawn


def reviews_with_current(node: dict[str, Any], role: str, critic_record: dict[str, Any]) -> dict[str, Any]:
    reviews = dict(node.get("critic_reviews") if isinstance(node.get("critic_reviews"), dict) else {})
    reviews[role] = {
        "critic_ref": critic_record["critic_ref"],
        "critic_id": critic_record["critic_id"],
        "critic_role": role,
        "verdict": critic_record["verdict"],
        "completed_at": critic_record["completed_at"],
        "evidence_fingerprint": critic_record["evidence_fingerprint"],
        "critic_result_path": critic_record["critic_result_path"],
        "spawn_model": critic_record.get("spawn_model"),
        "spawn_reasoning_effort": critic_record.get("spawn_reasoning_effort"),
    }
    return reviews


def all_required_roles_accepted(config: dict[str, Any], reviews: dict[str, Any], fingerprint: str) -> bool:
    for role in required_critic_roles(config):
        review = reviews.get(role)
        if not isinstance(review, dict):
            return False
        if review.get("verdict") != "ACCEPT":
            return False
        if review.get("evidence_fingerprint") != fingerprint:
            return False
    return True


def next_repair_id_for_state(phase_state: dict[str, Any], node_id: str) -> str:
    repairs = phase_state.get("repairs") if isinstance(phase_state.get("repairs"), dict) else {}
    prefix = f"repair-{node_id}-"
    count = sum(1 for repair_id in repairs if str(repair_id).startswith(prefix))
    return f"{prefix}{count + 1:03d}"


def create_repair_assignment(
    target: Path,
    run_id: str,
    node_id: str,
    *,
    critic_record: dict[str, Any] | None = None,
    required_revisions: list[Any] | None = None,
    reason: str,
) -> dict[str, Any]:
    state = load_loop_state(target, run_id)
    phase_state = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else {}
    repair_id = next_repair_id_for_state(phase_state, node_id)
    result_path = research_pending_path(target, run_id, "repairs", repair_id)
    ensure_pending_file(result_path)
    repair = {
        "repair_id": repair_id,
        "node_id": node_id,
        "status": "pending",
        "created_at": utc_now(),
        "critic_ref": critic_record.get("critic_ref") if critic_record else None,
        "critic_id": critic_record.get("critic_id") if critic_record else None,
        "required_revisions": list(required_revisions or []),
        "result_path": str(result_path),
        "reason": reason,
    }

    node = read_node(target, run_id, node_id)
    node.update(
        {
            "status": "repairing",
            "open_repair_id": repair_id,
            "requires_worker_repair": True,
            "repair_result_path": str(result_path),
            "required_revisions": list(required_revisions or []),
        }
    )
    write_node(target, run_id, node_id, node)

    def mutator(new_state: dict[str, Any]) -> None:
        new_phase = new_state.setdefault("state", {})
        repairs = new_phase.setdefault("repairs", {})
        repairs[repair_id] = repair
        nodes = new_phase.setdefault("nodes", {})
        node_state = nodes.setdefault(node_id, {})
        node_state.update(
            {
                "status": "repairing",
                "updated_at": utc_now(),
                "open_repair_id": repair_id,
                "requires_worker_repair": True,
                "repair_result_path": str(result_path),
                "required_revisions": list(required_revisions or []),
            }
        )
        orchestrator = new_phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "node_repair"
        orchestrator["next_action_details"] = {
            "reason": reason,
            "node_id": node_id,
            "repair_id": repair_id,
            "result_path": str(result_path),
            "required_revisions": list(required_revisions or []),
        }
        orchestrator["current_node"] = node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "node repair assignment", "repair_id": repair_id, "reason": reason}, mutator, node_id=node_id)
    return repair


def research_mode_critic_template(config: dict[str, Any]) -> str:
    mode = str(config.get("strictness_mode") or "scientist")
    template = nested_value(config, ["research", "modes", mode, "node_critic_prompt_template"])
    if isinstance(template, str) and template.strip():
        return template
    return RESEARCH_NODE_CRITIC_PROMPTS.get(mode, RESEARCH_NODE_CRITIC_PROMPTS["scientist"])


def build_node_critic_prompt(config: dict[str, Any], node_id: str, critic_id: str, result_path: Path, fingerprint: str, role: str, rubric: dict[str, Any]) -> str:
    template = research_mode_critic_template(config)
    mode = str(config.get("strictness_mode") or "scientist")
    return (
        template.format(node_id=node_id, mode=mode, critic_id=critic_id, evidence_fingerprint=fingerprint, result_path=str(result_path))
        + "\n\n"
        + role_guidance(role)
        + "\n\nFrozen rubric snapshot:\n"
        + json.dumps(rubric, indent=2, sort_keys=True)
        + "\n\nFrozen target venue bar:\n"
        + target_venue_summary(config)
        + "\n\nReturn JSON only to the assigned result_path with this schema:\n"
        '{ "verdict": "ACCEPT|REVISE|INVALID|REJECT", "critic_role": "'
        + role
        + '", "mode": "'
        + mode
        + '", "score": 0-100, "rationale": "...", '
        '"acceptance_checks": {"metric_contract_valid": true, "split_integrity_valid": true, "leakage_check_valid": true, '
        '"all_trials_accounted_for": true, "claim_matches_evidence": true, "mode_specific_bar_met": true, '
        '"cheap_improvements_remaining": false}, '
        '"missed_opportunity_scan": {"searched": ["..."], "actionable_improvements": [], "why_remaining_ideas_are_not_worth_running": "..."}, '
        '"strengths": ["..."], "weaknesses": ["..."], "required_revisions": ["..."], "risk_flags": ["..."] }\n'
        f"Node evidence fingerprint: {fingerprint}\n"
        f"Result path: {result_path}\n"
        "Do not assume the node is final or accepted. ACCEPT means this role's required evidence is complete under the frozen rubric. "
        "REVISE means meaningful progress, partial success, incomplete implementation, missing validation, a plausible next approach, or cheap actionable improvement remains. "
        "Do not treat an underperforming or half-built implementation as hypothesis_failed_with_evidence. That outcome requires evidence that the frozen hypothesis is fundamentally false under the current data/contract, not merely that this approach needs more work or a different node. "
        "INVALID means the evidence cannot be trusted. REJECT means it is not worth continuing or not selected."
    )


def _bool_check(value: Any, label: str, expected: bool = True) -> str | None:
    if value is not expected:
        return f"{label} must be {str(expected).lower()}"
    return None


def critic_acceptance_reason(critic: dict[str, Any], config: dict[str, Any], pending: dict[str, Any], node: dict[str, Any]) -> str | None:
    mode = strictness_mode(config)
    role = str(pending.get("critic_role") or "")
    if critic.get("mode") != mode:
        return f"critic mode must be {mode}"
    if critic.get("critic_role") != role:
        return f"critic_role must be {role}"
    score = critic.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        return "critic score must be an integer 0..100"
    checks = critic.get("acceptance_checks")
    if not isinstance(checks, dict):
        return "ACCEPT requires acceptance_checks"
    for key in sorted(REQUIRED_ACCEPTANCE_CHECKS):
        reason = _bool_check(checks.get(key), f"acceptance_checks.{key}")
        if reason:
            return reason
    reason = _bool_check(checks.get("cheap_improvements_remaining"), "acceptance_checks.cheap_improvements_remaining", expected=False)
    if reason:
        return reason
    scan = critic.get("missed_opportunity_scan")
    if not isinstance(scan, dict):
        return "ACCEPT requires missed_opportunity_scan"
    searched = scan.get("searched")
    if not isinstance(searched, list) or not searched:
        return "missed_opportunity_scan.searched must be non-empty"
    actionable = scan.get("actionable_improvements")
    if not isinstance(actionable, list):
        return "missed_opportunity_scan.actionable_improvements must be a list"
    if actionable:
        return "ACCEPT cannot include actionable_improvements"
    if not isinstance(scan.get("why_remaining_ideas_are_not_worth_running"), str) or not scan["why_remaining_ideas_are_not_worth_running"].strip():
        return "missed_opportunity_scan must explain why remaining ideas are not worth running"
    if mode in PAPER_MODES:
        contract_reason = research_contract_reason(config)
        if contract_reason:
            return contract_reason
        outcome = node.get("outcome_type")
        if outcome not in PAPER_OUTCOME_TYPES:
            return "paper-mode ACCEPT requires paper outcome_type"
        for key in ("current_claim", "claim_equivalence", "contract_evidence", "paper_worthiness"):
            if not node.get(key):
                return f"paper-mode ACCEPT requires node.{key}"
        if node.get("worker_completion_state") == "incomplete" or node.get("implementation_complete") is False:
            return "paper-mode ACCEPT requires complete implementation evidence, not an incomplete worker result"
        if role == "claim_critic":
            verdict = critic.get("original_hypothesis_verdict")
            if verdict not in {"supported", "failed", "rescue"}:
                return "claim_critic ACCEPT requires original_hypothesis_verdict supported|failed|rescue"
            if critic.get("paper_worthy") is not True:
                return "claim_critic ACCEPT requires paper_worthy=true"
            if outcome == "hypothesis_supported" and critic.get("contract_success_met") is not True:
                return "hypothesis_supported requires contract_success_met=true"
            if outcome == "hypothesis_failed_with_evidence":
                if critic.get("contract_failure_met") is not True or critic.get("fundamental_failure") is not True:
                    return "hypothesis_failed_with_evidence requires contract_failure_met=true and fundamental_failure=true"
                evidence = node.get("contract_evidence") if isinstance(node.get("contract_evidence"), dict) else {}
                if evidence.get("routine_optimization_failure") is True or evidence.get("implementation_failure") is True:
                    return "hypothesis_failed_with_evidence cannot be based on routine optimization or implementation failure"
                if evidence.get("fundamental_failure_not_implementation_failure") is not True:
                    return "hypothesis_failed_with_evidence requires fundamental_failure_not_implementation_failure=true"
                alternatives = node.get("alternative_approaches_considered")
                if not isinstance(alternatives, list) or not alternatives:
                    return "hypothesis_failed_with_evidence requires alternative_approaches_considered"
            if outcome == "rescue_finding_with_failed_hypothesis":
                if critic.get("contract_failure_met") is not True or critic.get("rescue_scope_met") is not True:
                    return "rescue_finding_with_failed_hypothesis requires failure and rescue scope evidence"
    elif mode in {"builder", "engineer"}:
        if node.get("outcome_type") not in {"practical_improvement"}:
            return "builder/engineer ACCEPT requires practical_improvement outcome_type"
        strong = node.get("strong_model_evidence")
        if not isinstance(strong, dict):
            return "builder/engineer ACCEPT requires strong_model_evidence"
        if strong.get("cheap_improvements_remaining") is not False:
            return "strong_model_evidence.cheap_improvements_remaining must be false"
        if strong.get("tuning_plateau_or_exhausted") is not True:
            return "strong_model_evidence.tuning_plateau_or_exhausted must be true"
        min_trials = int(performance_bar_config(config).get("min_confirmation_trials") or 1)
        confirmations = strong.get("confirmation_trials")
        if isinstance(confirmations, list):
            confirmation_count = len(confirmations)
        else:
            confirmation_count = int(strong.get("confirmation_trial_count") or 0)
        if confirmation_count < min_trials:
            return f"strong_model_evidence requires at least {min_trials} confirmation trial(s)"
    return None


def validate_critic_payload(payload: dict[str, Any], config: dict[str, Any], pending: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    critic = payload.get("critic") if isinstance(payload.get("critic"), dict) else payload
    if not isinstance(critic, dict):
        raise CliError("critic payload must be a JSON object")
    verdict = critic.get("verdict")
    if verdict not in CRITIC_VERDICTS:
        raise CliError("critic verdict must be one of ACCEPT, REVISE, INVALID, REJECT")
    rationale = critic.get("rationale") or critic.get("reason")
    if not isinstance(rationale, str) or not rationale.strip():
        raise CliError("critic payload requires non-empty rationale")
    if verdict == "REVISE" and not critic.get("required_revisions"):
        raise CliError("REVISE critic payload requires required_revisions")
    if verdict == "ACCEPT":
        reason = critic_acceptance_reason(critic, config, pending, node)
        if reason:
            raise CliError(f"ACCEPT critic payload invalid: {reason}")
    return critic


def apply_node_status(
    target: Path,
    run_id: str,
    node_id: str,
    status: str,
    payload: dict[str, Any],
    *,
    reason: str | None = None,
    critic_record: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Path]:
    node = read_node(target, run_id, node_id)
    pending_path = Path(node["result_path"]) if isinstance(node.get("result_path"), str) else research_pending_path(target, run_id, "nodes", node_id)
    node_payload = payload.get("node", payload)
    node.update(node_payload if isinstance(node_payload, dict) else {})
    node.setdefault("result_path", str(ensure_pending_file(pending_path)))
    if critic_record is not None:
        role = str(critic_record.get("critic_role") or "performance_auditor")
        reviews = reviews_with_current(node, role, critic_record)
        node.update(
            {
                "critic_ref": critic_record["critic_ref"],
                "critic_id": critic_record["critic_id"],
                "critic_role": role,
                "critic_verdict": critic_record["verdict"],
                "critic_completed_at": critic_record["completed_at"],
                "critic_evidence_fingerprint": critic_record["evidence_fingerprint"],
                "critic_result_path": critic_record["critic_result_path"],
                "critic_reviews": reviews,
            }
        )
        if status == "accepted" and node.get("requires_fresh_critic"):
            node["requires_fresh_critic"] = False
    if status == "candidate" and node.get("requires_worker_repair"):
        node["requires_worker_repair"] = False
        node.pop("open_repair_id", None)
    node["status"] = status
    if reason:
        if status in {"rejected", "invalid"}:
            node.setdefault("rejection_reason", reason)
        else:
            node["reason"] = reason
    write_node(target, run_id, node_id, node)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        nodes = phase_state.setdefault("nodes", {})
        current = nodes.setdefault(node_id, {})
        current.update({"status": status, "updated_at": utc_now(), "result_path": str(pending_path)})
        if critic_record is not None:
            role = str(critic_record.get("critic_role") or "performance_auditor")
            reviews = reviews_with_current({**current, **node}, role, critic_record)
            current.update(
                {
                    "critic_ref": critic_record["critic_ref"],
                    "critic_id": critic_record["critic_id"],
                    "critic_role": role,
                    "critic_verdict": critic_record["verdict"],
                    "critic_completed_at": critic_record["completed_at"],
                    "critic_evidence_fingerprint": critic_record["evidence_fingerprint"],
                    "critic_result_path": critic_record["critic_result_path"],
                    "node_evidence_fingerprint": critic_record["evidence_fingerprint"],
                    "critic_reviews": reviews,
                }
            )
            if status == "accepted" and current.get("requires_fresh_critic"):
                current["requires_fresh_critic"] = False
        if status == "candidate" and current.get("requires_worker_repair"):
            current["requires_worker_repair"] = False
            current.pop("open_repair_id", None)
        if reason:
            key = "rejection_reason" if status in {"rejected", "invalid"} else "reason"
            current[key] = reason
        if status == "accepted":
            phase_state.setdefault("selection", {}).setdefault("status", "pending")

    mutate_loop_state(target, run_id, "state_transition", {"command": "node transition", "status": status, "reason": reason}, mutator, node_id=node_id)
    return node, pending_path



def cmd_node_plan_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    ensure_usage_cap_allows_new_work(target, run_id, command="node plan-start")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    payload = load_payload(args)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    plan_id = args.plan_id or next_sequence_id(phase_state, "plans", f"plan-{args.node_id}-")
    result_path = research_pending_path(target, run_id, "plans", plan_id)
    ensure_pending_file(result_path)
    prompt = build_node_architecture_plan_prompt(target, run_id, args.node_id, plan_id, result_path, payload, cfg)
    pending = {
        "plan_id": plan_id,
        "node_id": args.node_id,
        "status": "pending",
        "created_at": utc_now(),
        "result_path": str(result_path),
        "prompt": prompt,
        "objective": payload.get("objective") or payload.get("approach") or payload.get("summary"),
        "target_venue": target_venue_config(cfg),
    }

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        plans = phase.setdefault("plans", {})
        if plan_id in plans:
            raise CliError(f"plan already exists: {plan_id}")
        plans[plan_id] = pending
        nodes = phase.setdefault("nodes", {})
        node_state = nodes.setdefault(args.node_id, {})
        node_state.update({"status": "planning", "updated_at": utc_now(), "plan_id": plan_id, "architecture_plan_result_path": str(result_path)})
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "node_architecture_plan"
        orchestrator["next_action_details"] = {"reason": "node requires plan-first architecture before implementation", "node_id": args.node_id, "plan_id": plan_id, "result_path": str(result_path)}
        orchestrator["current_node"] = args.node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    node = read_node(target, run_id, args.node_id)
    node.update({"status": "planning", "plan_id": plan_id, "architecture_plan_result_path": str(result_path), "result_path": node.get("result_path") or str(research_pending_path(target, run_id, "nodes", args.node_id))})
    write_node(target, run_id, args.node_id, node)
    mutate_loop_state(target, run_id, "state_transition", {"command": "node plan-start", "plan_id": plan_id}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, node_id=args.node_id, plan_id=plan_id, result_path=str(result_path), prompt=prompt)


def cmd_node_plan_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    plans = phase_state.get("plans") if isinstance(phase_state.get("plans"), dict) else {}
    pending = plans.get(args.plan_id)
    if not isinstance(pending, dict):
        raise CliError(f"unknown pending plan: {args.plan_id}")
    result_path = Path(pending["result_path"]) if isinstance(pending.get("result_path"), str) else research_pending_path(target, run_id, "plans", args.plan_id)
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"plan payload is required at {result_path}")
    node_id = str(pending.get("node_id") or payload.get("node_id") or "")
    if payload.get("node_id") not in {None, node_id}:
        raise CliError("plan payload node_id mismatch")
    plan = payload.get("architecture_plan") if isinstance(payload.get("architecture_plan"), dict) else payload
    steps = architecture_steps(plan)
    completed_at = utc_now()
    record = {**pending, "status": "completed", "completed_at": completed_at, "payload": payload, "architecture_plan": {**plan, "implementation_steps": steps}, "payload_ref": str(result_path)}
    log_path = plan_log_path(target, run_id, args.plan_id)
    atomic_write_json(log_path, record)
    node = read_node(target, run_id, node_id)
    node.update({"status": "planned", "architecture_plan_ref": str(log_path), "architecture_plan": record["architecture_plan"], "implementation_step_index": 0, "implementation_steps_total": len(steps)})
    write_node(target, run_id, node_id, node)

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        phase.setdefault("plans", {})[args.plan_id] = record
        nodes = phase.setdefault("nodes", {})
        node_state = nodes.setdefault(node_id, {})
        node_state.update({"status": "planned", "updated_at": utc_now(), "architecture_plan_ref": str(log_path), "implementation_step_index": 0, "implementation_steps_total": len(steps)})
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "node_implementation_step"
        orchestrator["next_action_details"] = {"reason": "architecture plan complete; start first implementation step", "node_id": node_id, "plan_id": args.plan_id, "step_index": 0, "step": steps[0]}
        orchestrator["current_node"] = node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "node plan-complete", "plan_id": args.plan_id}, mutator, node_id=node_id)
    return response("ok", run_id=run_id, node_id=node_id, plan_id=args.plan_id, plan_ref=str(log_path), next_step=steps[0])


def cmd_node_step_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    ensure_usage_cap_allows_new_work(target, run_id, command="node step-start")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    node = read_node(target, run_id, args.node_id)
    plan = node.get("architecture_plan") if isinstance(node.get("architecture_plan"), dict) else None
    if not plan:
        raise CliError("node step-start requires completed architecture_plan")
    steps = architecture_steps(plan)
    index = args.step_index if args.step_index is not None else int(node.get("implementation_step_index") or 0)
    if index < 0 or index >= len(steps):
        raise CliError("implementation step index is out of range")
    step = steps[index]
    step_id = args.step_id or f"step-{args.node_id}-{index + 1:03d}-{uuid.uuid4().hex[:8]}"
    result_path = research_pending_path(target, run_id, "implementation-steps", step_id)
    ensure_pending_file(result_path)
    prompt = build_node_step_prompt(target, run_id, args.node_id, step_id, result_path, plan, step, cfg)
    pending = {"step_id": step_id, "node_id": args.node_id, "status": "pending", "step_index": index, "step": step, "created_at": utc_now(), "result_path": str(result_path), "prompt": prompt, "target_venue": target_venue_config(cfg)}

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        steps_state = phase.setdefault("implementation_steps", {})
        if step_id in steps_state:
            raise CliError(f"implementation step already exists: {step_id}")
        steps_state[step_id] = pending
        nodes = phase.setdefault("nodes", {})
        node_state = nodes.setdefault(args.node_id, {})
        node_state.update({"status": "implementing", "updated_at": utc_now(), "active_step_id": step_id, "implementation_step_index": index})
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "node_implementation_step"
        orchestrator["next_action_details"] = {"reason": "worker should implement one bounded architecture step", "node_id": args.node_id, "step_id": step_id, "step_index": index, "result_path": str(result_path)}
        orchestrator["current_node"] = args.node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    node.update({"status": "implementing", "active_step_id": step_id, "implementation_step_index": index})
    write_node(target, run_id, args.node_id, node)
    mutate_loop_state(target, run_id, "state_transition", {"command": "node step-start", "step_id": step_id}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, node_id=args.node_id, step_id=step_id, result_path=str(result_path), prompt=prompt)


def cmd_node_step_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    steps_state = phase_state.get("implementation_steps") if isinstance(phase_state.get("implementation_steps"), dict) else {}
    pending = steps_state.get(args.step_id)
    if not isinstance(pending, dict):
        raise CliError(f"unknown implementation step: {args.step_id}")
    result_path = Path(pending["result_path"]) if isinstance(pending.get("result_path"), str) else research_pending_path(target, run_id, "implementation-steps", args.step_id)
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"implementation step payload is required at {result_path}")
    node_id = str(pending.get("node_id") or payload.get("node_id") or "")
    if payload.get("node_id") not in {None, node_id}:
        raise CliError("implementation step payload node_id mismatch")
    node = read_node(target, run_id, node_id)
    total = int(node.get("implementation_steps_total") or 0)
    index = int(pending.get("step_index") or 0)
    step_complete = payload.get("step_complete") is True
    done_definition_met = payload.get("done_definition_met") is True or payload.get("node_done") is True
    recommended = str(payload.get("recommended_status") or "implementing")
    next_index = index + 1 if step_complete else index
    completed_at = utc_now()
    record_status = "completed" if step_complete else "continued"
    record = {**pending, "status": record_status, "completed_at": completed_at, "payload": payload, "payload_ref": str(result_path), "next_step_index": next_index}
    log_path = implementation_step_log_path(target, run_id, args.step_id)
    recorded_findings = record_payload_findings(target, run_id, node_id, payload, str(log_path))
    if recorded_findings:
        record["findings_recorded"] = recorded_findings
    atomic_write_json(log_path, record)
    node.update({"last_step_id": args.step_id, "last_step_log_ref": str(log_path), "implementation_step_index": min(next_index, total), "worker_completion_state": "complete" if done_definition_met else "incomplete"})
    optimization_attempts = payload.get("optimization_attempts") if isinstance(payload.get("optimization_attempts"), list) else []
    if optimization_attempts:
        existing_attempts = node.get("optimization_attempts") if isinstance(node.get("optimization_attempts"), list) else []
        node["optimization_attempts"] = existing_attempts + optimization_attempts
    if isinstance(payload.get("optimization_not_applicable_reason"), str) and payload["optimization_not_applicable_reason"].strip():
        node["optimization_not_applicable_reason"] = payload["optimization_not_applicable_reason"]
    spawned = payload.get("spawned_node_ideas") if isinstance(payload.get("spawned_node_ideas"), list) else []
    if spawned:
        node["spawned_node_ideas"] = spawned
    write_node(target, run_id, node_id, node)

    if done_definition_met and recommended == "candidate":
        candidate_payload = payload.get("node") if isinstance(payload.get("node"), dict) else payload.get("node_evidence")
        if not isinstance(candidate_payload, dict):
            raise CliError("candidate step completion requires node evidence payload under node or node_evidence")
        candidate_payload.setdefault("worker_completion_state", "complete")
        candidate_payload.setdefault("architecture_plan_done", True)
        apply_node_status(target, run_id, node_id, "candidate", {"node": candidate_payload}, reason=args.reason or "architecture plan implementation complete")
        final_status = "candidate"
        next_action = "node_critic"
        next_details = {"reason": "node implementation is complete; start independent critic", "node_id": node_id}
    else:
        final_status = "implementing"
        next_action = "node_implementation_step"
        next_details = {"reason": "node implementation is incomplete; keep going", "node_id": node_id, "step_index": min(next_index, max(total - 1, 0)), "remaining_work": payload.get("remaining_work", [])}

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        phase.setdefault("implementation_steps", {})[args.step_id] = record
        nodes = phase.setdefault("nodes", {})
        node_state = nodes.setdefault(node_id, {})
        node_state.update({"status": final_status, "updated_at": utc_now(), "implementation_step_index": min(next_index, total), "last_step_id": args.step_id, "last_step_log_ref": str(log_path), "worker_completion_state": "complete" if done_definition_met else "incomplete"})
        if spawned:
            node_state["spawned_node_ideas"] = spawned
        if optimization_attempts:
            existing_attempts = node_state.get("optimization_attempts") if isinstance(node_state.get("optimization_attempts"), list) else []
            node_state["optimization_attempts"] = existing_attempts + optimization_attempts
        if isinstance(payload.get("optimization_not_applicable_reason"), str) and payload["optimization_not_applicable_reason"].strip():
            node_state["optimization_not_applicable_reason"] = payload["optimization_not_applicable_reason"]
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = next_action
        orchestrator["next_action_details"] = next_details
        orchestrator["current_node"] = node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "node step-complete", "step_id": args.step_id, "status": final_status}, mutator, node_id=node_id)
    return response("ok", run_id=run_id, node_id=node_id, step_id=args.step_id, node_status=final_status, step_ref=str(log_path), next_action=next_action, spawned_node_ideas=spawned)


def node_optimization_evidence(target: Path, run_id: str, node_id: str, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    attempts = []
    for source in (node, payload or {}):
        values = source.get("optimization_attempts") if isinstance(source.get("optimization_attempts"), list) else []
        attempts.extend(item for item in values if isinstance(item, dict) or isinstance(item, str))
        trials = source.get("tuning_trials") if isinstance(source.get("tuning_trials"), list) else []
        attempts.extend({"source": "tuning_trials", "trial": item} for item in trials)
    strong = node.get("strong_model_evidence") if isinstance(node.get("strong_model_evidence"), dict) else {}
    if strong.get("tuning_plateau_or_exhausted") is True:
        attempts.append({"source": "strong_model_evidence", "conclusion": "tuning_plateau_or_exhausted"})
    optimization_findings = [item for item in load_findings(target, run_id, node_id=node_id, limit=50) if item.get("kind") == "optimization"]
    attempts.extend({"source": "findings", "summary": item.get("summary")} for item in optimization_findings)
    non_applicable_reason = None
    for source in (payload or {}, node):
        reason = source.get("optimization_not_applicable_reason")
        if isinstance(reason, str) and reason.strip():
            non_applicable_reason = reason.strip()
            break
    ok = bool(attempts) or bool(non_applicable_reason)
    return {
        "ok": ok,
        "optimization_attempts": attempts,
        "optimization_not_applicable_reason": non_applicable_reason,
        "required_before_revision": "optimization_attempts or optimization_not_applicable_reason",
    }


def validate_revision_alternatives(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise CliError("revision proposal requires 1-3 alternative approaches")
    if len(value) > 3:
        raise CliError("revision proposal alternatives are capped at 3")
    normalized = []
    seen = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise CliError("each revision alternative must be an object")
        alternative_id = str(item.get("alternative_id") or item.get("id") or f"alt-{index:03d}").strip()
        if not alternative_id:
            raise CliError("each revision alternative requires alternative_id")
        if alternative_id in seen:
            raise CliError(f"duplicate revision alternative_id: {alternative_id}")
        seen.add(alternative_id)
        title = str(item.get("title") or item.get("approach") or "").strip()
        rationale = str(item.get("scientific_rationale") or item.get("rationale") or "").strip()
        venue_fit = str(item.get("venue_fit") or item.get("target_venue_fit") or item.get("why_matches_target_venue_bar") or "").strip()
        not_hacking = str(item.get("why_not_metric_hacking") or "").strip()
        not_drift = str(item.get("why_not_claim_drift") or "").strip()
        missing = []
        if not title:
            missing.append("title")
        if not rationale:
            missing.append("scientific_rationale")
        if not venue_fit:
            missing.append("venue_fit")
        if not not_hacking:
            missing.append("why_not_metric_hacking")
        if not not_drift:
            missing.append("why_not_claim_drift")
        if missing:
            raise CliError(f"revision alternative {alternative_id} missing fields: {', '.join(missing)}")
        normalized.append({**item, "alternative_id": alternative_id, "title": title, "scientific_rationale": rationale, "venue_fit": venue_fit, "why_not_metric_hacking": not_hacking, "why_not_claim_drift": not_drift})
    return normalized


def validate_revision_payload(payload: dict[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    revision = payload.get("revision") if isinstance(payload.get("revision"), dict) else payload
    if not isinstance(revision, dict):
        raise CliError("revision payload must be a JSON object")
    node_id = str(pending.get("node_id") or "")
    if revision.get("node_id") not in {None, node_id}:
        raise CliError("revision payload node_id mismatch")
    why = str(revision.get("why_current_direction_insufficient") or revision.get("insufficiency_reason") or "").strip()
    if not why:
        raise CliError("revision proposal requires why_current_direction_insufficient")
    useful_findings = revision.get("useful_findings")
    if not isinstance(useful_findings, list):
        raise CliError("revision proposal requires useful_findings list")
    attempts = revision.get("optimization_attempts") if isinstance(revision.get("optimization_attempts"), list) else []
    non_applicable = revision.get("optimization_not_applicable_reason")
    if not attempts and not (isinstance(non_applicable, str) and non_applicable.strip()):
        raise CliError("revision proposal requires optimization_attempts or optimization_not_applicable_reason")
    alternatives = validate_revision_alternatives(revision.get("alternative_approaches") or revision.get("alternatives"))
    return {**revision, "node_id": node_id, "why_current_direction_insufficient": why, "useful_findings": useful_findings, "alternative_approaches": alternatives}


def build_revision_prompt(target: Path, run_id: str, revision_id: str, node_id: str, result_path: Path, node: dict[str, Any], config: dict[str, Any], optimization_evidence: dict[str, Any]) -> str:
    return (
        "You are brainstorming a revision for one AI Scientist research node. A revision is a different approach and always creates a new node after critic approval.\n"
        "Before revision, same-node work must already have covered reasonable debugging, tuning, layer/model variants within the same mechanism, ablations, or a documented reason those are not applicable.\n"
        "Propose one to three alternatives only. Each alternative must clear the frozen target-venue bar, avoid metric hacking, and avoid silent claim drift.\n"
        "Do not keep branching a lineage whose only path is incremental performance hacking below the venue bar. Record useful findings even if the current direction failed.\n\n"
        f"Run id: {run_id}\nNode id: {node_id}\nRevision id: {revision_id}\nTarget repo: {target}\nResult path: {result_path}\n"
        f"Selected idea id: {selected_idea_id_from_config(config)}\n\n"
        "Frozen target venue bar:\n"
        + target_venue_summary(config)
        + "\n\nSame-node optimization evidence:\n"
        + json.dumps(optimization_evidence, indent=2, sort_keys=True)
        + "\n\nCurrent node snapshot:\n"
        + json.dumps(node, indent=2, sort_keys=True)
        + "\n\nRelevant run findings:\n"
        + findings_context(target, run_id, node_id=node_id, limit=30)
        + "\n\nWrite JSON only to result_path with this schema:\n"
        '{"node_id":"...","revision_id":"...","optimization_attempts":[{"change":"...","metrics":{"before":0,"after":0},"conclusion":"..."}],'
        '"useful_findings":["..."],"why_current_direction_insufficient":"...",'
        '"alternative_approaches":[{"alternative_id":"alt-001","title":"...","scientific_rationale":"...","expected_mechanism":"...",'
        '"venue_fit":"...","why_not_metric_hacking":"...","why_not_claim_drift":"...","risk":"..."}],'
        '"findings":[{"kind":"positive|negative|optimization|bug|drift|exhaustion|transferable","summary":"...","transferable":true}]}\n'
    )


def build_revision_critic_prompt(target: Path, run_id: str, critic_id: str, revision: dict[str, Any], result_path: Path, config: dict[str, Any]) -> str:
    return (
        "You are the revision critic for an AI Scientist research lineage. Decide whether this node needs more same-direction work, may branch, or should stop.\n"
        "Use the frozen target venue as a hard threshold. Lower bars may accept honest incremental work; AAAI/IJCAI and top-ML bars require stronger novelty, mechanism, ablations, and less tolerance for tuning-only ideas.\n"
        "Return CONTINUE_NODE if more debugging/tuning/ablations within the same mechanism are still required before revision.\n"
        "Return BRANCH only for one to three approved alternatives that are viable and paper-worthy under the frozen venue bar.\n"
        "Return STOP_DRIFTED if continued branching is mostly performance hacking, claim drift, or below the venue threshold.\n"
        "Return STOP_EXHAUSTED if evidence indicates the goal is fundamentally unachievable under the current data/contract.\n\n"
        f"Run id: {run_id}\nCritic id: {critic_id}\nRevision id: {revision.get('revision_id')}\nNode id: {revision.get('node_id')}\nTarget repo: {target}\nResult path: {result_path}\n\n"
        "Frozen target venue bar:\n"
        + target_venue_summary(config)
        + "\n\nRevision proposal:\n"
        + json.dumps(revision, indent=2, sort_keys=True)
        + "\n\nRelevant run findings:\n"
        + findings_context(target, run_id, node_id=str(revision.get("node_id") or ""), limit=30)
        + "\n\nWrite JSON only to result_path with this schema:\n"
        '{"verdict":"CONTINUE_NODE|BRANCH|STOP_DRIFTED|STOP_EXHAUSTED","rationale":"...",'
        '"selected_alternative_ids":["alt-001"],"venue_bar_assessment":"...","paper_worthiness_assessment":"...",'
        '"drift_assessment":"...","required_same_node_work":["..."],"stop_reason":"..."}\n'
    )


def cmd_node_revision_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    ensure_usage_cap_allows_new_work(target, run_id, command="node revision-start")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    payload = load_payload(args)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    if args.node_id not in nodes and load_json_if_exists(node_json_path(target, run_id, args.node_id)) is None:
        raise CliError(f"unknown node for revision: {args.node_id}")
    node = read_node(target, run_id, args.node_id)
    if node_has_lineage_stop(node):
        raise CliError(f"lineage is stopped for node {args.node_id}: {node.get('lineage_stop')}")
    if isinstance(payload.get("optimization_attempts"), list):
        existing_attempts = node.get("optimization_attempts") if isinstance(node.get("optimization_attempts"), list) else []
        node["optimization_attempts"] = existing_attempts + payload["optimization_attempts"]
    if isinstance(payload.get("optimization_not_applicable_reason"), str) and payload["optimization_not_applicable_reason"].strip():
        node["optimization_not_applicable_reason"] = payload["optimization_not_applicable_reason"]
    optimization = node_optimization_evidence(target, run_id, args.node_id, node, payload)
    if not optimization["ok"]:
        raise CliError("revision-start requires optimization_attempts or optimization_not_applicable_reason before branching")
    write_node(target, run_id, args.node_id, node)
    revision_id = args.revision_id or next_sequence_id(phase_state, "revisions", f"revision-{args.node_id}-")
    result_path = research_pending_path(target, run_id, "revisions", revision_id)
    ensure_pending_file(result_path)
    prompt = build_revision_prompt(target, run_id, revision_id, args.node_id, result_path, node, cfg, optimization)
    pending = {
        "revision_id": revision_id,
        "node_id": args.node_id,
        "status": "pending",
        "created_at": utc_now(),
        "result_path": str(result_path),
        "prompt": prompt,
        "optimization_evidence": optimization,
        "target_venue": target_venue_config(cfg),
    }

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        revisions = phase.setdefault("revisions", {})
        if revision_id in revisions:
            raise CliError(f"revision already exists: {revision_id}")
        revisions[revision_id] = pending
        nodes_state = phase.setdefault("nodes", {})
        node_state = nodes_state.setdefault(args.node_id, {})
        node_state.update({"open_revision_id": revision_id, "updated_at": utc_now()})
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "node_revision_brainstorm"
        orchestrator["next_action_details"] = {"reason": "same-node optimization evidence exists; brainstorm venue-worthy revision alternatives", "node_id": args.node_id, "revision_id": revision_id, "result_path": str(result_path)}
        orchestrator["current_node"] = args.node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "node revision-start", "revision_id": revision_id}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, node_id=args.node_id, revision_id=revision_id, result_path=str(result_path), prompt=prompt, optimization_evidence=optimization)


def cmd_node_revision_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    revisions = phase_state.get("revisions") if isinstance(phase_state.get("revisions"), dict) else {}
    pending = revisions.get(args.revision_id)
    if not isinstance(pending, dict):
        raise CliError(f"unknown revision: {args.revision_id}")
    result_path = Path(pending["result_path"]) if isinstance(pending.get("result_path"), str) else research_pending_path(target, run_id, "revisions", args.revision_id)
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"revision payload is required at {result_path}")
    revision = validate_revision_payload(payload, pending)
    revision["revision_id"] = args.revision_id
    completed_at = utc_now()
    log_path = revision_log_path(target, run_id, args.revision_id)
    recorded_findings = record_payload_findings(target, run_id, revision["node_id"], payload.get("revision") if isinstance(payload.get("revision"), dict) else payload, str(log_path))
    record = {**pending, "status": "proposed", "completed_at": completed_at, "payload": payload, "proposal": revision, "payload_ref": str(result_path), "revision_ref": str(log_path)}
    if recorded_findings:
        record["findings_recorded"] = recorded_findings
    atomic_write_json(log_path, record)

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        phase.setdefault("revisions", {})[args.revision_id] = record
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "revision_critic"
        orchestrator["next_action_details"] = {"reason": "revision proposal ready for critic", "node_id": revision["node_id"], "revision_id": args.revision_id, "revision_ref": str(log_path)}
        orchestrator["current_node"] = revision["node_id"]
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "node revision-complete", "revision_id": args.revision_id}, mutator, node_id=revision["node_id"])
    return response("ok", run_id=run_id, node_id=revision["node_id"], revision_id=args.revision_id, revision_status="proposed", revision_ref=str(log_path), alternative_count=len(revision["alternative_approaches"]))


def cmd_node_revision_critic_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    ensure_usage_cap_allows_new_work(target, run_id, command="node revision-critic-start")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    revisions = phase_state.get("revisions") if isinstance(phase_state.get("revisions"), dict) else {}
    revision_record = revisions.get(args.revision_id)
    if not isinstance(revision_record, dict):
        raise CliError(f"unknown revision: {args.revision_id}")
    if revision_record.get("status") != "proposed":
        raise CliError(f"revision-critic-start requires proposed revision, found {revision_record.get('status')}")
    revision = revision_record.get("proposal") if isinstance(revision_record.get("proposal"), dict) else {}
    critic_id = args.critic_id or f"revision-critic-{args.revision_id}-{uuid.uuid4().hex[:8]}"
    result_path = research_pending_path(target, run_id, "revision-critics", critic_id)
    ensure_pending_file(result_path)
    prompt = build_revision_critic_prompt(target, run_id, critic_id, revision, result_path, cfg)
    pending = {"critic_id": critic_id, "revision_id": args.revision_id, "node_id": revision_record.get("node_id"), "status": "pending", "started_at": utc_now(), "result_path": str(result_path), "prompt": prompt, "target_venue": target_venue_config(cfg)}

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        critics = phase.setdefault("pending_revision_critics", {})
        if critic_id in critics:
            raise CliError(f"revision critic already exists: {critic_id}")
        critics[critic_id] = pending
        phase.setdefault("revisions", {})[args.revision_id] = {**revision_record, "status": "critic_pending", "open_revision_critic_id": critic_id}

    mutate_loop_state(target, run_id, "critic_event", {"command": "node revision-critic-start", "critic_id": critic_id, "revision_id": args.revision_id}, mutator, node_id=str(revision_record.get("node_id") or ""))
    return response("ok", run_id=run_id, revision_id=args.revision_id, critic_id=critic_id, result_path=str(result_path), prompt=prompt)


def validate_revision_critic_payload(payload: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    critic = payload.get("critic") if isinstance(payload.get("critic"), dict) else payload
    if not isinstance(critic, dict):
        raise CliError("revision critic payload must be a JSON object")
    verdict = critic.get("verdict")
    if verdict not in REVISION_VERDICTS:
        raise CliError("revision critic verdict must be one of CONTINUE_NODE, BRANCH, STOP_DRIFTED, STOP_EXHAUSTED")
    rationale = str(critic.get("rationale") or critic.get("reason") or "").strip()
    if not rationale:
        raise CliError("revision critic payload requires rationale")
    alternatives = revision.get("alternative_approaches") if isinstance(revision.get("alternative_approaches"), list) else []
    alternatives_by_id = {item.get("alternative_id"): item for item in alternatives if isinstance(item, dict)}
    selected = critic.get("selected_alternative_ids") or critic.get("approved_alternative_ids") or []
    if verdict == "BRANCH":
        if not isinstance(selected, list) or not selected:
            raise CliError("BRANCH revision critic requires selected_alternative_ids")
        if len(selected) > 3:
            raise CliError("BRANCH revision critic can approve at most 3 alternatives")
        unknown = [str(item) for item in selected if item not in alternatives_by_id]
        if unknown:
            raise CliError("BRANCH selected unknown alternative ids: " + ", ".join(unknown))
    elif selected:
        raise CliError(f"{verdict} revision critic must not select branch alternatives")
    return {**critic, "verdict": verdict, "rationale": rationale, "selected_alternative_ids": [str(item) for item in selected]}


def cmd_node_revision_critic_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    pending_critics = phase_state.get("pending_revision_critics") if isinstance(phase_state.get("pending_revision_critics"), dict) else {}
    pending = pending_critics.get(args.critic_id)
    if not isinstance(pending, dict):
        raise CliError(f"unknown pending revision critic: {args.critic_id}")
    revisions = phase_state.get("revisions") if isinstance(phase_state.get("revisions"), dict) else {}
    revision_record = revisions.get(pending.get("revision_id"))
    if not isinstance(revision_record, dict):
        raise CliError(f"unknown revision for critic: {pending.get('revision_id')}")
    revision = revision_record.get("proposal") if isinstance(revision_record.get("proposal"), dict) else {}
    result_path = Path(pending["result_path"]) if isinstance(pending.get("result_path"), str) else research_pending_path(target, run_id, "revision-critics", args.critic_id)
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"revision critic payload is required at {result_path}")
    critic = validate_revision_critic_payload(payload, revision)
    verdict = critic["verdict"]
    selected_ids = critic.get("selected_alternative_ids", [])
    alternatives = revision.get("alternative_approaches") if isinstance(revision.get("alternative_approaches"), list) else []
    alternatives_by_id = {item.get("alternative_id"): item for item in alternatives if isinstance(item, dict)}
    approved = [alternatives_by_id[item] for item in selected_ids]
    completed_at = utc_now()
    log_path = revision_critic_log_path(target, run_id, args.critic_id)
    status_by_verdict = {
        "CONTINUE_NODE": "continue_node",
        "BRANCH": "branch_approved",
        "STOP_DRIFTED": "stopped_drifted",
        "STOP_EXHAUSTED": "stopped_exhausted",
    }
    revision_update = {
        **revision_record,
        "status": status_by_verdict[verdict],
        "critic_id": args.critic_id,
        "critic_ref": str(log_path),
        "critic_verdict": verdict,
        "critic": critic,
        "approved_alternative_ids": selected_ids,
        "approved_alternatives": approved,
        "completed_critic_at": completed_at,
    }
    record = {"schema_version": 1, "run_id": run_id, "critic_id": args.critic_id, "revision_id": pending.get("revision_id"), "node_id": pending.get("node_id"), "verdict": verdict, "critic": critic, "revision_ref": revision_record.get("revision_ref"), "critic_result_path": str(result_path), "started_at": pending.get("started_at"), "completed_at": completed_at, "status": status_by_verdict[verdict]}
    atomic_write_json(log_path, record)
    node_id = str(pending.get("node_id") or revision.get("node_id") or "")
    node = read_node(target, run_id, node_id) if node_id else {}
    if verdict in {"STOP_DRIFTED", "STOP_EXHAUSTED"} and node_id:
        node["lineage_stop"] = {"verdict": verdict, "reason": critic["rationale"], "critic_ref": str(log_path), "stopped_at": completed_at}
        write_node(target, run_id, node_id, node)
    elif verdict == "CONTINUE_NODE" and node_id:
        node["status"] = "implementing"
        node["revision_continue_reason"] = critic["rationale"]
        write_node(target, run_id, node_id, node)

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        phase.setdefault("revisions", {})[str(pending.get("revision_id"))] = revision_update
        phase.setdefault("pending_revision_critics", {}).pop(args.critic_id, None)
        nodes = phase.setdefault("nodes", {})
        if node_id:
            node_state = nodes.setdefault(node_id, {})
            node_state["updated_at"] = utc_now()
            node_state["last_revision_id"] = pending.get("revision_id")
            node_state["last_revision_critic_ref"] = str(log_path)
            if verdict == "CONTINUE_NODE":
                node_state["status"] = "implementing"
                node_state["revision_continue_reason"] = critic["rationale"]
            elif verdict in {"STOP_DRIFTED", "STOP_EXHAUSTED"}:
                node_state["lineage_stop"] = {"verdict": verdict, "reason": critic["rationale"], "critic_ref": str(log_path), "stopped_at": completed_at}
        orchestrator = phase.setdefault("orchestrator", {})
        if verdict == "CONTINUE_NODE":
            orchestrator["next_action"] = "node_implementation_step"
            details = {"reason": critic["rationale"], "node_id": node_id, "revision_id": pending.get("revision_id"), "required_same_node_work": critic.get("required_same_node_work", [])}
        elif verdict == "BRANCH":
            orchestrator["next_action"] = "node_branch"
            details = {"reason": critic["rationale"], "node_id": node_id, "revision_id": pending.get("revision_id"), "approved_alternative_ids": selected_ids}
        else:
            orchestrator["next_action"] = "lineage_stopped"
            details = {"reason": critic["rationale"], "node_id": node_id, "revision_id": pending.get("revision_id"), "verdict": verdict}
        orchestrator["next_action_details"] = details
        orchestrator["current_node"] = node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "critic_event", {"command": "node revision-critic-complete", "critic_id": args.critic_id, "verdict": verdict}, mutator, node_id=node_id)
    append_journal_event(target, run_id, "critic_event", node_id=node_id, details={"command": "node revision-critic-log", "critic_id": args.critic_id, "revision_id": pending.get("revision_id"), "verdict": verdict, "critic_ref": str(log_path)})
    return response("ok", run_id=run_id, node_id=node_id, revision_id=pending.get("revision_id"), critic_id=args.critic_id, verdict=verdict, revision_status=status_by_verdict[verdict], approved_alternative_ids=selected_ids, critic_ref=str(log_path))


def cmd_node_branch(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    if not args.revision_id or not args.alternative_id:
        raise CliError("node branch requires --revision-id and --alternative-id from a BRANCH revision critic verdict")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    revisions = phase_state.get("revisions") if isinstance(phase_state.get("revisions"), dict) else {}
    revision = revisions.get(args.revision_id)
    if not isinstance(revision, dict):
        raise CliError(f"unknown revision: {args.revision_id}")
    if revision.get("status") != "branch_approved" or revision.get("critic_verdict") != "BRANCH":
        raise CliError("node branch requires revision critic verdict BRANCH")
    parent_node_id = str(args.from_node or revision.get("node_id") or "")
    if not parent_node_id:
        raise CliError("branch parent node is missing")
    if args.from_node and args.from_node != revision.get("node_id"):
        raise CliError("--from-node does not match revision parent node")
    parent = read_node(target, run_id, parent_node_id)
    if node_has_lineage_stop(parent):
        raise CliError(f"lineage is stopped for node {parent_node_id}: {parent.get('lineage_stop')}")
    approved = revision.get("approved_alternatives") if isinstance(revision.get("approved_alternatives"), list) else []
    alternative = next((item for item in approved if isinstance(item, dict) and item.get("alternative_id") == args.alternative_id), None)
    if not isinstance(alternative, dict):
        raise CliError(f"alternative {args.alternative_id} is not approved for revision {args.revision_id}")
    created = revision.get("created_branch_node_ids") if isinstance(revision.get("created_branch_node_ids"), dict) else {}
    if args.alternative_id in created:
        raise CliError(f"alternative already branched: {args.alternative_id} -> {created[args.alternative_id]}")
    payload = load_payload(args)
    node_id = args.node_id
    if load_json_if_exists(node_json_path(target, run_id, node_id)) is not None:
        raise CliError(f"node already exists: {node_id}")
    pending_path = research_pending_path(target, run_id, "nodes", node_id)
    ensure_pending_file(pending_path)
    branch_reason = args.reason or payload.get("reason") or revision.get("critic", {}).get("rationale")
    node_payload = {
        "node_id": node_id,
        "status": "planning",
        "parent_node_id": parent_node_id,
        "revision_id": args.revision_id,
        "alternative_id": args.alternative_id,
        "branch_reason": branch_reason,
        "approach": payload.get("approach") or alternative.get("title") or payload.get("title") or payload.get("summary"),
        "revision_alternative": alternative,
        "target_venue": target_venue_config(cfg),
        "result_path": str(pending_path),
        "created_at": utc_now(),
    }
    node_payload.update(payload.get("node", {}) if isinstance(payload.get("node"), dict) else {})
    write_node(target, run_id, node_id, node_payload)
    created = {**created, args.alternative_id: node_id}
    revision_update = {**revision, "created_branch_node_ids": created}
    if isinstance(revision.get("revision_ref"), str):
        atomic_write_json(Path(revision["revision_ref"]), revision_update)

    def mutator(new_state: dict[str, Any]) -> None:
        phase = new_state.setdefault("state", {})
        phase.setdefault("revisions", {})[args.revision_id] = revision_update
        nodes = phase.setdefault("nodes", {})
        nodes[node_id] = {"status": "planning", "updated_at": utc_now(), "parent_node_id": parent_node_id, "revision_id": args.revision_id, "alternative_id": args.alternative_id, "result_path": str(pending_path), "branch_reason": branch_reason, "target_venue": target_venue_config(cfg)}
        queue = phase.setdefault("node_queue", [])
        if isinstance(queue, list) and node_id not in queue:
            queue.append(node_id)
        orchestrator = phase.setdefault("orchestrator", {})
        orchestrator["next_action"] = "node_architecture_plan"
        orchestrator["next_action_details"] = {"reason": "critic-approved research direction created from revision", "node_id": node_id, "parent_node_id": parent_node_id, "revision_id": args.revision_id, "alternative_id": args.alternative_id}
        orchestrator["current_node"] = node_id
        orchestrator["last_checkpoint_at"] = utc_now()

    mutate_loop_state(target, run_id, "state_transition", {"command": "node branch", "node_id": node_id, "from_node": parent_node_id, "revision_id": args.revision_id, "alternative_id": args.alternative_id}, mutator, node_id=node_id)
    return response("ok", run_id=run_id, node_id=node_id, node_status="planning", parent_node_id=parent_node_id, revision_id=args.revision_id, alternative_id=args.alternative_id, result_path=str(pending_path))

def cmd_node_transition(args: argparse.Namespace) -> int:
    if args.status not in NODE_STATUSES:
        raise CliError(f"invalid node status: {args.status}")
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    if args.status in NODE_USAGE_GATED_STATUSES:
        ensure_usage_cap_allows_new_work(target, run_id, command=f"node transition {args.status}")
    node = read_node(target, run_id, args.node_id)
    pending_path = Path(node["result_path"]) if isinstance(node.get("result_path"), str) else research_pending_path(target, run_id, "nodes", args.node_id)
    payload = load_payload_or_path(args, pending_path)
    if args.status in NODE_TERMINAL_STATUSES:
        raise CliError(f"terminal node status {args.status} requires node critic-complete")
    if args.status == "candidate" and node.get("requires_worker_repair"):
        repair_id = node.get("open_repair_id")
        state = load_loop_state(target, run_id)
        phase_state = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else {}
        repairs = phase_state.get("repairs") if isinstance(phase_state.get("repairs"), dict) else {}
        repair = repairs.get(repair_id) if isinstance(repairs.get(repair_id), dict) else None
        if not repair or repair.get("status") != "completed":
            raise CliError(f"candidate transition requires completed worker repair payload: {repair_id}")
    apply_node_status(target, run_id, args.node_id, args.status, payload, reason=args.reason)
    return response("ok", run_id=run_id, node_id=args.node_id, node_status=args.status, node_path=str(node_json_path(target, run_id, args.node_id)), result_path=str(pending_path))


def cmd_node_critic_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    ensure_usage_cap_allows_new_work(target, run_id, command="node critic-start")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    node = read_node(target, run_id, args.node_id)
    role = args.role or default_critic_role(cfg, node)
    if role not in CRITIC_ROLES:
        raise CliError(f"invalid critic role: {role}")
    if role not in required_critic_roles(cfg):
        raise CliError(f"critic role {role} is not required for {strictness_mode(cfg)} mode")
    fingerprint = node_evidence_fingerprint(node)
    critic_id = args.critic_id or f"critic-{args.node_id}-{uuid.uuid4().hex[:12]}"
    result_path = research_pending_path(target, run_id, "critics", critic_id)
    ensure_pending_file(result_path)
    runtime = critic_agent_config(cfg)
    rubric = rubric_snapshot(cfg, role)
    prompt = build_node_critic_prompt(cfg, args.node_id, critic_id, result_path, fingerprint, role, rubric)
    pending = {
        "critic_id": critic_id,
        "node_id": args.node_id,
        "critic_role": role,
        "status": "pending",
        "started_at": utc_now(),
        "result_path": str(result_path),
        "evidence_fingerprint": fingerprint,
        "prompt": prompt,
        "required_runtime": runtime,
        "rubric_snapshot": rubric,
    }

    def mutator(new_state: dict[str, Any]) -> None:
        phase_state = new_state.setdefault("state", {})
        pending_critics = phase_state.setdefault("pending_critics", {})
        if critic_id in pending_critics:
            raise CliError(f"critic already exists: {critic_id}")
        pending_critics[critic_id] = pending

    mutate_loop_state(target, run_id, "critic_event", {"command": "node critic-start", "critic_id": critic_id, "critic_role": role}, mutator, node_id=args.node_id)
    return response(
        "ok",
        run_id=run_id,
        node_id=args.node_id,
        critic_id=critic_id,
        critic_role=role,
        required_model=runtime["model"],
        required_reasoning_effort=runtime["reasoning_effort"],
        result_path=str(result_path),
        evidence_fingerprint=fingerprint,
        rubric_snapshot=rubric,
        prompt=prompt,
    )


def cmd_node_critic_spawn_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    pending_critics = phase_state.get("pending_critics") if isinstance(phase_state.get("pending_critics"), dict) else {}
    pending = pending_critics.get(args.critic_id)
    if not isinstance(pending, dict):
        raise CliError(f"unknown pending critic: {args.critic_id}")
    required = pending.get("required_runtime") if isinstance(pending.get("required_runtime"), dict) else DEFAULT_CRITIC_AGENT
    if args.model != required.get("model"):
        raise CliError(f"critic spawn model mismatch: expected {required.get('model')}, found {args.model}")
    if args.reasoning_effort != required.get("reasoning_effort"):
        raise CliError(f"critic spawn reasoning effort mismatch: expected {required.get('reasoning_effort')}, found {args.reasoning_effort}")
    spawn = {
        "agent_id": args.agent_id,
        "spawn_model": args.model,
        "spawn_reasoning_effort": args.reasoning_effort,
        "spawned_at": utc_now(),
    }

    def mutator(new_state: dict[str, Any]) -> None:
        critics = new_state.setdefault("state", {}).setdefault("pending_critics", {})
        if args.critic_id not in critics:
            raise CliError(f"unknown pending critic: {args.critic_id}")
        critics[args.critic_id]["spawn"] = spawn

    mutate_loop_state(target, run_id, "critic_event", {"command": "node critic-spawn-record", "critic_id": args.critic_id, "agent_id": args.agent_id}, mutator)
    return response("ok", run_id=run_id, critic_id=args.critic_id, agent_id=args.agent_id, spawn=spawn)


def cmd_node_critic_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    pending_critics = phase_state.get("pending_critics") if isinstance(phase_state.get("pending_critics"), dict) else {}
    pending = pending_critics.get(args.critic_id)
    if not isinstance(pending, dict):
        raise CliError(f"unknown pending critic: {args.critic_id}")
    node_id = str(pending.get("node_id") or "")
    if not node_id:
        raise CliError(f"pending critic missing node_id: {args.critic_id}")
    result_path = Path(pending["result_path"]) if isinstance(pending.get("result_path"), str) else research_pending_path(target, run_id, "critics", args.critic_id)
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    spawn = validate_critic_spawn(pending, cfg)
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"critic result payload is required at {result_path}")
    node = read_node(target, run_id, node_id)
    fingerprint = node_evidence_fingerprint(node)
    expected = pending.get("evidence_fingerprint")
    if fingerprint != expected:
        raise CliError(f"critic result is stale for node evidence: expected {expected}, found {fingerprint}")
    critic = validate_critic_payload(payload, cfg, pending, node)
    verdict = str(critic["verdict"])
    role = str(pending.get("critic_role") or default_critic_role(cfg, node))
    completed_at = utc_now()
    log_path = critic_log_path(target, run_id, args.critic_id)
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "critic_id": args.critic_id,
        "node_id": node_id,
        "critic_role": role,
        "verdict": verdict,
        "critic": critic,
        "evidence_fingerprint": fingerprint,
        "critic_result_path": str(result_path),
        "required_runtime": pending.get("required_runtime"),
        "spawn": spawn,
        "rubric_snapshot": pending.get("rubric_snapshot"),
        "started_at": pending.get("started_at"),
        "completed_at": completed_at,
    }
    rationale = str(critic.get("rationale") or critic.get("reason") or "")
    if verdict == "REVISE":
        reason = "; ".join(map(str, critic.get("required_revisions") or [])) or rationale
    else:
        reason = rationale
    critic_record = {
        "critic_ref": str(log_path),
        "critic_id": args.critic_id,
        "critic_role": role,
        "verdict": verdict,
        "completed_at": completed_at,
        "evidence_fingerprint": fingerprint,
        "critic_result_path": str(result_path),
        "spawn_model": spawn.get("spawn_model"),
        "spawn_reasoning_effort": spawn.get("spawn_reasoning_effort"),
    }
    if verdict == "ACCEPT":
        reviews = reviews_with_current(node, role, critic_record)
        status = "accepted" if all_required_roles_accepted(cfg, reviews, fingerprint) else "candidate"
        reason = rationale if status == "accepted" else f"{role} accepted; waiting for remaining critic roles"
    else:
        status = CRITIC_STATUS_BY_VERDICT[verdict]
    record["status"] = status
    atomic_write_json(log_path, record)
    apply_node_status(target, run_id, node_id, status, {}, reason=reason, critic_record=critic_record)
    repair = None
    if verdict == "REVISE":
        repair = create_repair_assignment(
            target,
            run_id,
            node_id,
            critic_record=critic_record,
            required_revisions=list(critic.get("required_revisions") or []),
            reason=reason,
        )

    def mutator(new_state: dict[str, Any]) -> None:
        new_pending = new_state.setdefault("state", {}).setdefault("pending_critics", {})
        new_pending.pop(args.critic_id, None)

    mutate_loop_state(target, run_id, "critic_event", {"command": "node critic-complete", "critic_id": args.critic_id, "critic_role": role, "verdict": verdict, "status": status}, mutator, node_id=node_id)
    append_journal_event(target, run_id, "critic_event", node_id=node_id, details={"command": "node critic-log", "critic_id": args.critic_id, "critic_role": role, "verdict": verdict, "critic_ref": str(log_path)})
    return response("ok", run_id=run_id, node_id=node_id, critic_id=args.critic_id, critic_role=role, verdict=verdict, node_status=status, critic_ref=str(log_path), repair=repair)


def cmd_node_create_workspace(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    baseline = run_dir(target, run_id) / "baseline-workspace"
    if not baseline.exists():
        raise CliError(f"missing baseline workspace: {baseline}")
    workspace = node_dir(target, run_id, args.node_id) / "workspace"
    if workspace.exists():
        raise CliError(f"node workspace already exists: {workspace}")
    shutil.copytree(baseline, workspace, symlinks=True)
    payload = {"workspace_path": str(workspace), "status": "planned"}
    args.status = "planned"
    args.json = json.dumps({"node": payload})
    args.json_file = None
    args.reason = args.reason or "node workspace created"
    return cmd_node_transition(args)


def cmd_node_repair_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    ensure_usage_cap_allows_new_work(target, run_id, command="node repair-start")
    node = read_node(target, run_id, args.node_id)
    if node.get("status") not in {"buggy", "repairing", "candidate"}:
        raise CliError(f"repair-start requires buggy/repairing/candidate node, found {node.get('status')}")
    revisions = []
    if args.required_revision:
        revisions = args.required_revision
    elif isinstance(node.get("required_revisions"), list):
        revisions = node["required_revisions"]
    repair = create_repair_assignment(target, run_id, args.node_id, required_revisions=revisions, reason=args.reason or "worker-owned node repair")
    return response("ok", run_id=run_id, node_id=args.node_id, repair_id=repair["repair_id"], result_path=repair["result_path"])


def cmd_node_repair_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    repairs = phase_state.get("repairs") if isinstance(phase_state.get("repairs"), dict) else {}
    repair = repairs.get(args.repair_id)
    if not isinstance(repair, dict):
        raise CliError(f"unknown repair assignment: {args.repair_id}")
    result_path = Path(repair["result_path"]) if isinstance(repair.get("result_path"), str) else research_pending_path(target, run_id, "repairs", args.repair_id)
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"repair payload is required at {result_path}")
    if payload.get("repair_id") not in {None, args.repair_id}:
        raise CliError("repair payload repair_id mismatch")
    node_id = str(repair.get("node_id") or payload.get("node_id") or "")
    if not node_id:
        raise CliError("repair assignment missing node_id")
    if payload.get("node_id") not in {None, node_id}:
        raise CliError("repair payload node_id mismatch")
    if not isinstance(payload.get("fixed_revisions"), list):
        raise CliError("repair payload requires fixed_revisions list")
    fixed_revisions = {str(item) for item in payload.get("fixed_revisions", [])}
    required_revisions = [str(item) for item in repair.get("required_revisions", []) if str(item)]
    explicit_remaining = payload.get("remaining_required_revisions")
    if explicit_remaining is not None and not isinstance(explicit_remaining, list):
        raise CliError("repair payload remaining_required_revisions must be a list when provided")
    remaining = [item for item in required_revisions if item not in fixed_revisions]
    if isinstance(explicit_remaining, list):
        for item in explicit_remaining:
            text = str(item)
            if text and text not in remaining:
                remaining.append(text)
    real_blocker = payload.get("real_blocker")
    has_real_blocker = isinstance(real_blocker, dict) and bool(real_blocker.get("reason") or real_blocker.get("type"))
    completed_at = utc_now()
    record_status = "completed"
    if remaining:
        record_status = "blocked" if has_real_blocker else "continued"
    record = {
        **repair,
        "status": record_status,
        "completed_at": completed_at,
        "payload": payload,
        "payload_ref": str(result_path),
        "remaining_required_revisions": remaining,
    }
    log_path = repair_log_path(target, run_id, args.repair_id)
    atomic_write_json(log_path, record)
    node = read_node(target, run_id, node_id)
    node.update(
        {
            "last_repair_id": args.repair_id,
            "last_repair_completed_at": completed_at,
            "repair_payload_ref": str(result_path),
            "repair_log_ref": str(log_path),
            "requires_worker_repair": True,
        }
    )
    write_node(target, run_id, node_id, node)

    def mutator(new_state: dict[str, Any]) -> None:
        new_phase = new_state.setdefault("state", {})
        state_repairs = new_phase.setdefault("repairs", {})
        state_repairs[args.repair_id] = record
        nodes = new_phase.setdefault("nodes", {})
        node_state = nodes.setdefault(node_id, {})
        node_state.update(
            {
                "last_repair_id": args.repair_id,
                "last_repair_completed_at": completed_at,
                "repair_payload_ref": str(result_path),
                "repair_log_ref": str(log_path),
                "requires_worker_repair": True,
            }
        )
        if has_real_blocker:
            orchestrator = new_phase.setdefault("orchestrator", {})
            orchestrator["next_action"] = "blocked_repair"
            orchestrator["next_action_details"] = {"reason": "worker repair blocked", "node_id": node_id, "repair_id": args.repair_id, "real_blocker": real_blocker}
            orchestrator["current_node"] = node_id
            new_state["phase_status"] = "blocked_repair"
            new_state["blocked_reason"] = real_blocker

    mutate_loop_state(target, run_id, "state_transition", {"command": "node repair-complete", "repair_id": args.repair_id}, mutator, node_id=node_id)
    followup = None
    if remaining and not has_real_blocker:
        followup = create_repair_assignment(
            target,
            run_id,
            node_id,
            required_revisions=remaining,
            reason="worker repair left required revisions unresolved; continue node repair",
        )
    return response("ok", run_id=run_id, node_id=node_id, repair_id=args.repair_id, repair_status=record_status, repair_ref=str(log_path), followup_repair=followup)


def cmd_subagent_update(args: argparse.Namespace) -> int:
    if args.status not in SUBAGENT_STATUSES:
        raise CliError(f"invalid subagent status: {args.status}")
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    if args.status in SUBAGENT_USAGE_GATED_STATUSES:
        ensure_usage_cap_allows_new_work(target, run_id, command=f"subagent update {args.status}")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    limit = research_max_subagents(cfg)
    state = load_loop_state(target, run_id)
    phase_state = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else {}
    subagents = phase_state.get("subagents") if isinstance(phase_state.get("subagents"), dict) else {}
    existing = subagents.get(args.subagent_id) if isinstance(subagents.get(args.subagent_id), dict) else {}
    pending_path = Path(existing["result_path"]) if isinstance(existing.get("result_path"), str) else research_pending_path(target, run_id, "subagents", args.subagent_id)
    payload = load_payload_or_path(args, pending_path)
    if args.status in {"completed_unintegrated", "failed_unreviewed"} and not payload and not getattr(args, "json", None) and not getattr(args, "json_file", None):
        raise CliError(f"{args.status} requires worker result payload in result_path or explicit --path/--json: {pending_path}")

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        subagents = phase_state.setdefault("subagents", {})
        current = subagents.setdefault(args.subagent_id, {})
        current.update(payload)
        current["status"] = args.status
        current["updated_at"] = utc_now()
        current["result_path"] = str(ensure_pending_file(pending_path))
        if args.node_id:
            current["node_id"] = args.node_id
        nonterminal = [
            subagent_id
            for subagent_id, subagent in subagents.items()
            if not isinstance(subagent, dict) or str(subagent.get("status") or "") not in SUBAGENT_TERMINAL_STATUSES
        ]
        if len(nonterminal) > limit:
            raise CliError(f"research subagent concurrency limit exceeded: {len(nonterminal)} > {limit}")

    mutate_loop_state(target, run_id, "subagent_event", {"command": "subagent update", "status": args.status}, mutator, node_id=args.node_id, subagent_id=args.subagent_id)
    return response("ok", run_id=run_id, subagent_id=args.subagent_id, subagent_status=args.status, result_path=str(pending_path))


def node_required_critic_reason(config: dict[str, Any], node: dict[str, Any], node_id: str) -> str | None:
    fingerprint = node_evidence_fingerprint(node)
    reviews = node.get("critic_reviews") if isinstance(node.get("critic_reviews"), dict) else {}
    missing = [role for role in required_critic_roles(config) if not isinstance(reviews.get(role), dict)]
    if missing:
        return f"accepted node missing required critic roles: {node_id}:{','.join(missing)}"
    for role in required_critic_roles(config):
        review = reviews[role]
        if review.get("verdict") != "ACCEPT":
            return f"accepted node critic role not accepted: {node_id}:{role}:{review.get('verdict')}"
        if review.get("evidence_fingerprint") != fingerprint:
            return f"accepted node critic role stale: {node_id}:{role}"
        if review.get("spawn_model") != critic_agent_config(config)["model"]:
            return f"accepted node critic role wrong model: {node_id}:{role}"
        if review.get("spawn_reasoning_effort") != critic_agent_config(config)["reasoning_effort"]:
            return f"accepted node critic role wrong reasoning effort: {node_id}:{role}"
    return None


def cmd_selection_finalize(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    payload = load_payload(args)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    selected = payload.get("selected_node") or args.selected_node
    if not isinstance(selected, str) or not selected:
        raise CliError("selected_node is required")
    if not isinstance(nodes.get(selected), dict) or nodes[selected].get("status") != "accepted":
        raise CliError("selected node must be accepted in loop-state.json")
    selected_doc = read_node(target, run_id, selected)
    role_reason = node_required_critic_reason(cfg, selected_doc, selected)
    if role_reason:
        raise CliError(role_reason)
    critic_reason = node_fresh_critic_reason(selected, nodes[selected], required_verdict="ACCEPT")
    if critic_reason:
        raise CliError(f"selected node must have fresh ACCEPT critic verdict: {critic_reason}")
    accepted_nodes = [node_id for node_id, node in nodes.items() if isinstance(node, dict) and node.get("status") == "accepted"]
    for node_id in accepted_nodes:
        node_doc = read_node(target, run_id, node_id)
        role_reason = node_required_critic_reason(cfg, node_doc, node_id)
        if role_reason:
            raise CliError(role_reason)
        critic_reason = node_fresh_critic_reason(node_id, nodes[node_id], required_verdict="ACCEPT")
        if critic_reason:
            raise CliError(f"accepted node must have fresh ACCEPT critic verdict: {critic_reason}")
    ranked = payload.get("ranked_nodes") or [{"node_id": node_id} for node_id in accepted_nodes]
    ranked_ids = [item.get("node_id") for item in ranked if isinstance(item, dict)]
    missing = sorted(set(accepted_nodes) - set(ranked_ids))
    if missing:
        raise CliError(f"selection is missing accepted nodes: {', '.join(missing)}")
    outcome_type = payload.get("outcome_type") or selected_doc.get("outcome_type")
    if outcome_type not in OUTCOME_TYPES:
        raise CliError("selection finalize requires valid outcome_type")
    metric_key = payload.get("metric_key")
    if not isinstance(metric_key, str) or not metric_key.strip():
        raise CliError("selection finalize requires metric_key")
    metric_direction = payload.get("metric_direction") or payload.get("direction")
    if metric_direction not in {"maximize", "minimize"}:
        raise CliError("selection finalize requires metric_direction maximize|minimize")
    for metric_field in ("baseline_metric", "selected_metric"):
        if metric_field not in payload:
            raise CliError(f"selection finalize requires {metric_field}")
        try:
            float(payload[metric_field])
        except (TypeError, ValueError) as exc:
            raise CliError(f"selection finalize requires numeric {metric_field}") from exc
    if not isinstance(payload.get("rationale"), str) or not payload["rationale"].strip():
        raise CliError("selection finalize requires rationale")
    selection = {
        "schema_version": 1,
        "run_id": run_id,
        "selection_status": "final",
        "provisional": False,
        "selected_node": selected,
        "outcome_type": outcome_type,
        "metric_key": metric_key,
        "metric_direction": metric_direction,
        "baseline_metric": payload.get("baseline_metric"),
        "selected_metric": payload.get("selected_metric"),
        "ranked_nodes": ranked,
        "rejected_or_superseded": payload.get("rejected_or_superseded", []),
        "manual_override": payload.get("manual_override"),
        "rationale": payload.get("rationale"),
        "updated_at": utc_now(),
    }
    atomic_write_json(selection_path(target, run_id), selection)

    def mutator(new_state: dict[str, Any]) -> None:
        new_phase_state = new_state.setdefault("state", {})
        new_phase_state["selected_node"] = selected
        new_phase_state["selection"] = {"status": "final", "selected_node": selected, "selection_ref": str(selection_path(target, run_id))}

    mutate_loop_state(target, run_id, "selection", {"command": "selection finalize", "selected_node": selected}, mutator, node_id=selected)
    return response("ok", run_id=run_id, selected_node=selected, selection_path=str(selection_path(target, run_id)))



def _dependency_error_message(status: dict[str, Any]) -> str:
    missing = []
    if status.get("missing_python"):
        missing.append("Python packages: " + ", ".join(str(item) for item in status["missing_python"]))
    if status.get("missing_executables"):
        missing.append("executables: " + ", ".join(str(item) for item in status["missing_executables"]))
    return "missing writeup dependency (" + "; ".join(missing) + "). Install the missing dependency and rerun this command."


def cmd_writeup_doctor(args: argparse.Namespace) -> int:
    status = writeup_dependency_status(include_tex=not args.skip_tex)
    if not status.get("ok"):
        return response("error", error=_dependency_error_message(status), dependencies=status)
    return response("ok", dependencies=status)


def cmd_writeup_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    state = start_writeup(target, args.run_id, require_pdf=True)
    return response("ok", run_id=args.run_id, state_path=str(run_dir(target, args.run_id) / "loop-state.json"), next_action=state.get("state", {}).get("orchestrator", {}).get("next_action"))


def cmd_writeup_resume(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    cursor = resume_writeup(target, run_id)
    if args.prompt:
        cursor["prompt"] = (
            "Continue the AI Scientist writeup phase from the listed next_action. "
            "Use the writeup CLI to record figures, reports, audit results, and completion."
        )
    return response("ok", **cursor)


def cmd_writeup_collect_figures(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    manifest = writeup_collect_figures(target, run_id)
    return response("ok", run_id=run_id, figure_manifest="writeup/figures/figure-manifest.json", figure_count=len(manifest.get("figures", [])))


def cmd_writeup_record_reports(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    manifest = writeup_record_reports(target, run_id, args.markdown, args.latex)
    return response("ok", run_id=run_id, manifest="writeup/manifest.json", require_pdf=manifest.get("require_pdf"))


def cmd_writeup_compile(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    log = writeup_compile_pdf(target, run_id, tex_path=args.tex)
    return response("ok", run_id=run_id, compile_log="writeup/compile-log.json", report_pdf=log.get("report_pdf"))


def cmd_writeup_audit_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    prompt = writeup_start_audit(target, run_id)
    return response("ok", run_id=run_id, pending_audit="writeup/audit/pending-final-audit.json", prompt=prompt)


def cmd_writeup_audit_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    payload = load_payload(args)
    audit = writeup_complete_audit(target, run_id, payload)
    return response("ok", run_id=run_id, audit="writeup/audit/final-audit.json", verdict=audit.get("verdict"))


def cmd_writeup_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    state = writeup_complete_writeup(target, run_id)
    return response("ok", run_id=run_id, state_path=str(run_dir(target, run_id) / "loop-state.json"), active=state.get("active"), phase_status=state.get("phase_status"), active_run_status="validating")


def cmd_writeup_negative_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _active = active_run(target, args.run_id)
    state = writeup_negative_complete(target, run_id, args.reason)
    return response("ok", run_id=run_id, active=state.get("active"), phase_status=state.get("phase_status"), reason=args.reason)


def cmd_finding_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    payload = load_payload(args)
    finding = dict(payload)
    finding["kind"] = args.kind or finding.get("kind")
    finding["summary"] = args.summary or finding.get("summary")
    finding["node_id"] = args.node_id or finding.get("node_id")
    finding["source_ref"] = args.source_ref or finding.get("source_ref")
    if args.transferable:
        finding["transferable"] = True
    record = append_finding(target, run_id, finding)
    return response("ok", run_id=run_id, finding=record, findings_jsonl=str(findings_jsonl_path(target, run_id)), findings_md=str(findings_md_path(target, run_id)))

def cmd_validation_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    append_journal_event(target, run_id, "validation", details={"gate": args.gate, "exit_code": args.exit_code, "validator_exit_code": args.exit_code, "command": args.command})
    return response("ok", run_id=run_id, gate=args.gate, exit_code=args.exit_code)


def cmd_handoff_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    approved = args.approved
    append_journal_event(
        target,
        run_id,
        "handoff",
        details={"gate": args.gate, "approved": approved, "exit_code": args.exit_code, "validator_exit_code": args.exit_code, "reason": args.reason},
    )
    if approved and state and state.get("phase_status") == "complete" and has_stop_release_evidence(target, run_id, str(state.get("phase") or "research")):
        clear_active_run(target, run_id)
    return response("ok", run_id=run_id, gate=args.gate, approved=approved)


def require_ideation_run(args: argparse.Namespace) -> tuple[Path, str]:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if state and state.get("phase") != "ideation":
        raise CliError(f"active run is not ideation: {state.get('phase')}")
    return target, run_id


def ideation_response(target: Path, run_id: str, **extra: Any) -> int:
    state = load_loop_state(target, run_id)
    cfg = current_config(target, run_id) if state and state.get("phase") == "ideation" else {}
    cursor = cursor_for_state(state, cfg) if isinstance(state, dict) and state.get("phase") == "ideation" else {}
    return response("ok", run_id=run_id, phase_status=state.get("phase_status") if isinstance(state, dict) else None, **cursor, **extra)


def cmd_ideation_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    state = start_ideation(
        target,
        args.run_id,
        args.prompt,
        mode=args.strictness_mode,
        num_ideas_required=args.num_ideas,
        min_candidates_required=args.min_candidates,
        reflection_budget=args.reflection_budget,
        max_subagents=args.max_subagents,
    )
    cfg = current_config(target, args.run_id)
    cursor = cursor_for_state(state, cfg)
    return response("ok", run_id=args.run_id, state_path=str(run_dir(target, args.run_id) / "loop-state.json"), config_path=str(config_path(target, args.run_id)), **cursor)


def cmd_ideation_resume(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    result = resume_ideation(target, run_id, prompt=args.prompt)
    return response("ok", **result)


def cmd_ideation_cancel(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    cancel_ideation(target, run_id, args.reason)
    return ideation_response(target, run_id)


def cmd_ideation_complete(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    complete_ideation(target, run_id, budget_exhausted=args.budget_exhausted)
    return ideation_response(target, run_id)


def cmd_ideation_exhaust(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    exhaust_ideation(target, run_id)
    return ideation_response(target, run_id)


def cmd_ideation_rank_finalize(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    finalize_ranking(target, run_id, payload)
    return ideation_response(target, run_id)


def cmd_ideation_rank_candidates(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    result = rank_candidates(target, run_id, mode=args.mode)
    return ideation_response(target, run_id, **result)


def cmd_ideation_finalize_ready(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    finalize_ready(target, run_id, idea_ids=args.idea_ids)
    return ideation_response(target, run_id)


def cmd_ideation_intent_start(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    intent = start_intent(target, run_id, args.role, idea_id=args.idea_id, agent_thread_id=args.agent_thread_id)
    return ideation_response(target, run_id, intent=intent)


def cmd_ideation_intent_start_batch(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    batch = start_intent_batch(
        target,
        run_id,
        args.role,
        count=args.count,
        idea_ids=args.idea_ids,
        agent_thread_id=args.agent_thread_id,
    )
    return ideation_response(target, run_id, **batch)


def cmd_ideation_intent_complete(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    complete_intent(target, run_id, payload, intent_id=args.intent_id)
    return ideation_response(target, run_id)


def cmd_ideation_intent_cancel(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    cancel_intent(target, run_id, args.reason, intent_id=args.intent_id)
    return ideation_response(target, run_id)


def cmd_idea_draft(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    idea_payload = payload.get("idea") if isinstance(payload.get("idea"), dict) else payload
    record_draft(target, run_id, idea_payload, idea_id=args.idea_id)
    return ideation_response(target, run_id)


def cmd_idea_revise_start(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    start_revision(target, run_id, args.idea_id, args.reason)
    return ideation_response(target, run_id)


def cmd_idea_critic_record(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    critic_payload = payload.get("critic") if isinstance(payload.get("critic"), dict) else payload
    record_critic(target, run_id, critic_payload, idea_id=args.idea_id)
    return ideation_response(target, run_id)


def cmd_idea_search_semantic_scholar(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    if not payload and not args.query:
        raise CliError("search-semantic-scholar requires --query or a JSON evidence payload")
    record_semantic_scholar_search(
        target,
        run_id,
        idea_id=args.idea_id,
        query=args.query,
        evidence_payload=payload or None,
        limit=args.limit,
        provider=args.provider,
    )
    return ideation_response(target, run_id)


def cmd_idea_record_evidence_batch(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    payload = load_payload(args)
    record_evidence_batch(
        target,
        run_id,
        idea_ids=args.idea_ids,
        queries=args.queries,
        evidence_payload=payload or None,
        limit=args.limit,
        provider=args.provider,
    )
    return ideation_response(target, run_id)


def cmd_idea_finalize(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    finalize_idea(target, run_id, idea_id=args.idea_id)
    return ideation_response(target, run_id)


def cmd_idea_reject(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    reject_idea(target, run_id, idea_id=args.idea_id, reason=args.reason)
    return ideation_response(target, run_id)


def cmd_idea_exhaust(args: argparse.Namespace) -> int:
    target, run_id = require_ideation_run(args)
    exhaust_idea(target, run_id, idea_id=args.idea_id, reason=args.reason)
    return ideation_response(target, run_id)


def copy_ignore(_dir: str, names: list[str]) -> set[str]:
    ignored = {".git", ".ai-scientist", "__pycache__", ".pytest_cache", ".mypy_cache"}
    return {name for name in names if name in ignored}


def cmd_workspace_init(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    source = Path(args.source).resolve()
    baseline = run_dir(target, run_id) / "baseline-workspace"
    if baseline.exists():
        raise CliError(f"baseline workspace already exists: {baseline}")
    shutil.copytree(source, baseline, symlinks=True, ignore=copy_ignore)
    cfg = load_json_if_exists(config_path(target, run_id))
    if isinstance(cfg, dict):
        cfg.setdefault("workspace", {})["baseline_workspace"] = str(baseline)
        atomic_write_json(config_path(target, run_id), cfg)

    def mutator(state: dict[str, Any]) -> None:
        state.setdefault("state", {})["workspace_plan_status"] = "complete"

    mutate_loop_state(target, run_id, "workspace", {"command": "workspace init", "source": str(source), "baseline_workspace": str(baseline)}, mutator)
    return response("ok", run_id=run_id, baseline_workspace=str(baseline))


def cmd_resource_run(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise CliError("resource run requires a command after --")
    cwd = Path(args.cwd).resolve() if args.cwd else target
    trial_dir = node_dir(target, run_id, args.node_id) / "trials" / args.trial_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = trial_dir / "stdout.log"
    stderr_path = trial_dir / "stderr.log"
    command_ref = trial_dir / "command.json"
    env = os.environ.copy()
    env_updates = json.loads(args.env_json) if args.env_json else {}
    if not isinstance(env_updates, dict):
        raise CliError("--env-json must be an object")
    env.update({str(key): str(value) for key, value in env_updates.items()})
    env_record = {str(key): str(value) for key, value in env_updates.items()}
    lease_id = None
    lease_path: Path | None = None
    if args.gpu:
        resource_dir = run_dir(target, run_id) / "resources"
        resource_dir.mkdir(parents=True, exist_ok=True)
        lease_id = f"gpu-0-{os.getpid()}-{args.node_id}-{args.trial_id}"
        lease_path = resource_dir / "gpu-0.lock"
        lease_payload = {"lease_id": lease_id, "pid": os.getpid(), "node_id": args.node_id, "trial_id": args.trial_id, "created_at": utc_now()}
        try:
            fd = os.open(lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise CliError(f"gpu resource busy: {lease_path}") from exc
        with os.fdopen(fd, "w") as handle:
            json.dump(lease_payload, handle, sort_keys=True)
            handle.write("\n")
        env.setdefault("CUDA_VISIBLE_DEVICES", "0")
        env_record.setdefault("CUDA_VISIBLE_DEVICES", env["CUDA_VISIBLE_DEVICES"])
    command_spec = {
        "argv": command,
        "cwd": str(cwd),
        "env": {key: env_record[key] for key in sorted(env_record)},
        "gpu_requested": args.gpu,
        "resource_lease_id": lease_id,
        "started_at": utc_now(),
    }
    command_spec["command_spec_hash"] = data_hash(command_spec)
    atomic_write_json(command_ref, command_spec)
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    finally:
        if lease_path is not None:
            try:
                lease_path.unlink()
            except FileNotFoundError:
                pass
    stdout_path.write_text(proc.stdout)
    stderr_path.write_text(proc.stderr)
    command_spec.update({"completed_at": utc_now(), "exit_code": proc.returncode, "stdout": str(stdout_path), "stderr": str(stderr_path)})
    atomic_write_json(command_ref, command_spec)
    metrics: dict[str, Any] | None = None
    if args.metrics_json:
        metrics = json.loads(args.metrics_json)
        metrics_source = "inline_metrics_json"
    elif args.metrics_path and Path(args.metrics_path).exists():
        metrics_value = json.loads(Path(args.metrics_path).read_text())
        if isinstance(metrics_value, dict):
            metrics = metrics_value
        metrics_source = str(args.metrics_path)
    else:
        metrics_source = None
    node = read_node(target, run_id, args.node_id)
    trials = node.setdefault("trials", [])
    trial_record = {
        "trial_id": args.trial_id,
        "purpose": args.purpose,
        "status": "completed" if proc.returncode == 0 else "failed",
        "command_ref": str(command_ref),
        "metrics": metrics,
        "metrics_ref": args.metrics_path,
        "metrics_source": metrics_source,
        "resource_lease_id": lease_id,
        "seed": args.seed,
        "started_at": command_spec["started_at"],
        "ended_at": command_spec["completed_at"],
        "benchmark_contract_version": args.benchmark_contract_version,
        "notes": args.notes,
    }
    trials.append({key: value for key, value in trial_record.items() if value is not None})
    write_node(target, run_id, args.node_id, node)
    append_journal_event(target, run_id, "resource_event", node_id=args.node_id, resource_id=lease_id, details={"command": "resource run", "trial_id": args.trial_id, "exit_code": proc.returncode, "gpu_requested": args.gpu, "resource_lease_id": lease_id, "command_spec_hash": command_spec["command_spec_hash"]})
    return response("ok" if proc.returncode == 0 else "error", run_id=run_id, node_id=args.node_id, trial_id=args.trial_id, exit_code=proc.returncode, command_ref=str(command_ref))


def add_json_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", help="Inline JSON object payload.")
    parser.add_argument("--json-file", type=Path, help="Path to JSON object payload.")
    parser.add_argument("--path", dest="json_file", type=Path, help="Alias for --json-file; useful for oversized payloads.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, help="Target repository. Defaults to current working directory.")
    sub = parser.add_subparsers(dest="area", required=True)

    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="command", required=True)
    start = research_sub.add_parser("start")
    start.add_argument("--run-id", required=True)
    start.add_argument("--strictness-mode")
    start.add_argument("--selected-idea-id")
    start.add_argument("--target-venue-preset")
    start.add_argument("--target-venue-name")
    start.add_argument("--target-venue-notes")
    start.add_argument("--token-budget-percent")
    start.add_argument("--max-subagents", type=int)
    start.add_argument("--no-limit-host-cap", action="store_true")
    add_json_args(start)
    start.set_defaults(func=cmd_research_start)
    resume = research_sub.add_parser("resume")
    resume.add_argument("--run-id")
    resume.set_defaults(func=cmd_research_resume)
    usage_check = research_sub.add_parser("usage-check")
    usage_check.add_argument("--run-id", required=True)
    usage_check.add_argument("--force", action="store_true")
    usage_check.set_defaults(func=cmd_research_usage_check)
    checkpoint = research_sub.add_parser("checkpoint")
    checkpoint.add_argument("--run-id")
    add_json_args(checkpoint)
    checkpoint.set_defaults(func=cmd_research_checkpoint)
    next_action = research_sub.add_parser("set-next-action")
    next_action.add_argument("--run-id")
    next_action.add_argument("--lane", required=True)
    next_action.add_argument("--reason")
    next_action.add_argument("--node-id")
    add_json_args(next_action)
    next_action.set_defaults(func=cmd_research_set_next_action)
    complete = research_sub.add_parser("complete")
    complete.add_argument("--run-id")
    add_json_args(complete)
    complete.set_defaults(func=cmd_research_complete)
    cancel = research_sub.add_parser("cancel")
    cancel.add_argument("--run-id")
    cancel.add_argument("--reason", required=True)
    cancel.set_defaults(func=cmd_research_cancel)

    ideation = sub.add_parser("ideation")
    ideation_sub = ideation.add_subparsers(dest="command", required=True)
    ideation_start = ideation_sub.add_parser("start")
    ideation_start.add_argument("--run-id", required=True)
    ideation_start.add_argument("--prompt", required=True)
    ideation_start.add_argument("--strictness-mode")
    ideation_start.add_argument("--num-ideas", type=int)
    ideation_start.add_argument("--min-candidates", type=int)
    ideation_start.add_argument("--reflection-budget", type=int)
    ideation_start.add_argument("--max-subagents", type=int)
    ideation_start.set_defaults(func=cmd_ideation_start)
    ideation_resume = ideation_sub.add_parser("resume")
    ideation_resume.add_argument("--run-id")
    ideation_resume.add_argument("--prompt", action="store_true")
    ideation_resume.set_defaults(func=cmd_ideation_resume)
    ideation_cancel = ideation_sub.add_parser("cancel")
    ideation_cancel.add_argument("--run-id")
    ideation_cancel.add_argument("--reason", required=True)
    ideation_cancel.set_defaults(func=cmd_ideation_cancel)
    ideation_complete = ideation_sub.add_parser("complete")
    ideation_complete.add_argument("--run-id")
    ideation_complete.add_argument("--budget-exhausted", action="store_true")
    ideation_complete.set_defaults(func=cmd_ideation_complete)
    ideation_exhaust = ideation_sub.add_parser("exhaust")
    ideation_exhaust.add_argument("--run-id")
    ideation_exhaust.set_defaults(func=cmd_ideation_exhaust)
    ideation_rank = ideation_sub.add_parser("rank-finalize")
    ideation_rank.add_argument("--run-id")
    add_json_args(ideation_rank)
    ideation_rank.set_defaults(func=cmd_ideation_rank_finalize)
    ideation_rank_candidates = ideation_sub.add_parser("rank-candidates")
    ideation_rank_candidates.add_argument("--run-id")
    ideation_rank_candidates.add_argument("--mode", choices=["deterministic", "agent"], default="deterministic")
    ideation_rank_candidates.set_defaults(func=cmd_ideation_rank_candidates)
    ideation_finalize_ready = ideation_sub.add_parser("finalize-ready")
    ideation_finalize_ready.add_argument("--run-id")
    ideation_finalize_ready.add_argument("--idea-ids", nargs="+")
    ideation_finalize_ready.set_defaults(func=cmd_ideation_finalize_ready)
    ideation_intent = ideation_sub.add_parser("intent")
    ideation_intent_sub = ideation_intent.add_subparsers(dest="intent_command", required=True)
    intent_start = ideation_intent_sub.add_parser("start")
    intent_start.add_argument("--run-id")
    intent_start.add_argument("--role", required=True, choices=sorted({"generator", "critic", "ranker"}))
    intent_start.add_argument("--idea-id")
    intent_start.add_argument("--agent-thread-id")
    intent_start.set_defaults(func=cmd_ideation_intent_start)
    intent_start_batch = ideation_intent_sub.add_parser("start-batch")
    intent_start_batch.add_argument("--run-id")
    intent_start_batch.add_argument("--role", required=True, choices=sorted({"generator", "critic"}))
    intent_start_batch.add_argument("--count", type=int)
    intent_start_batch.add_argument("--idea-ids", nargs="+")
    intent_start_batch.add_argument("--agent-thread-id")
    intent_start_batch.set_defaults(func=cmd_ideation_intent_start_batch)
    intent_complete = ideation_intent_sub.add_parser("complete")
    intent_complete.add_argument("--run-id")
    intent_complete.add_argument("--intent-id")
    add_json_args(intent_complete)
    intent_complete.set_defaults(func=cmd_ideation_intent_complete)
    intent_cancel = ideation_intent_sub.add_parser("cancel")
    intent_cancel.add_argument("--run-id")
    intent_cancel.add_argument("--intent-id")
    intent_cancel.add_argument("--reason", required=True)
    intent_cancel.set_defaults(func=cmd_ideation_intent_cancel)


    writeup = sub.add_parser("writeup")
    writeup_sub = writeup.add_subparsers(dest="command", required=True)
    writeup_doctor = writeup_sub.add_parser("doctor")
    writeup_doctor.add_argument("--skip-tex", action="store_true")
    writeup_doctor.set_defaults(func=cmd_writeup_doctor)
    writeup_start = writeup_sub.add_parser("start")
    writeup_start.add_argument("--run-id", required=True)
    writeup_start.set_defaults(func=cmd_writeup_start)
    writeup_resume = writeup_sub.add_parser("resume")
    writeup_resume.add_argument("--run-id")
    writeup_resume.add_argument("--prompt", action="store_true")
    writeup_resume.set_defaults(func=cmd_writeup_resume)
    writeup_figures = writeup_sub.add_parser("collect-figures")
    writeup_figures.add_argument("--run-id")
    writeup_figures.set_defaults(func=cmd_writeup_collect_figures)
    writeup_record = writeup_sub.add_parser("record-reports")
    writeup_record.add_argument("--run-id")
    writeup_record.add_argument("--markdown", type=Path, default=Path("writeup/report.md"))
    writeup_record.add_argument("--latex", type=Path, default=Path("writeup/latex/template.tex"))
    writeup_record.set_defaults(func=cmd_writeup_record_reports)
    writeup_compile = writeup_sub.add_parser("compile")
    writeup_compile.add_argument("--run-id")
    writeup_compile.add_argument("--tex", type=Path)
    writeup_compile.set_defaults(func=cmd_writeup_compile)
    writeup_audit_start = writeup_sub.add_parser("audit-start")
    writeup_audit_start.add_argument("--run-id")
    writeup_audit_start.set_defaults(func=cmd_writeup_audit_start)
    writeup_audit_complete = writeup_sub.add_parser("audit-complete")
    writeup_audit_complete.add_argument("--run-id")
    add_json_args(writeup_audit_complete)
    writeup_audit_complete.set_defaults(func=cmd_writeup_audit_complete)
    writeup_complete = writeup_sub.add_parser("complete")
    writeup_complete.add_argument("--run-id")
    writeup_complete.set_defaults(func=cmd_writeup_complete)
    writeup_negative = writeup_sub.add_parser("negative-complete")
    writeup_negative.add_argument("--run-id")
    writeup_negative.add_argument("--reason", required=True)
    writeup_negative.set_defaults(func=cmd_writeup_negative_complete)

    idea = sub.add_parser("idea")
    idea_sub = idea.add_subparsers(dest="command", required=True)
    idea_draft = idea_sub.add_parser("draft")
    idea_draft.add_argument("--run-id")
    idea_draft.add_argument("--idea-id")
    add_json_args(idea_draft)
    idea_draft.set_defaults(func=cmd_idea_draft)
    idea_revise = idea_sub.add_parser("revise-start")
    idea_revise.add_argument("--run-id")
    idea_revise.add_argument("--idea-id", required=True)
    idea_revise.add_argument("--reason")
    idea_revise.set_defaults(func=cmd_idea_revise_start)
    idea_critic = idea_sub.add_parser("critic-record")
    idea_critic.add_argument("--run-id")
    idea_critic.add_argument("--idea-id")
    add_json_args(idea_critic)
    idea_critic.set_defaults(func=cmd_idea_critic_record)
    idea_search = idea_sub.add_parser("search-semantic-scholar")
    idea_search.add_argument("--run-id")
    idea_search.add_argument("--idea-id")
    idea_search.add_argument("--query")
    idea_search.add_argument("--limit", type=int, default=10)
    idea_search.add_argument("--provider", choices=["auto", "semantic_scholar", "openalex"], default="auto")
    add_json_args(idea_search)
    idea_search.set_defaults(func=cmd_idea_search_semantic_scholar)
    idea_record_evidence_batch = idea_sub.add_parser("record-evidence-batch")
    idea_record_evidence_batch.add_argument("--run-id")
    idea_record_evidence_batch.add_argument("--idea-ids", nargs="+", required=True)
    idea_record_evidence_batch.add_argument("--queries", nargs="+", required=True)
    idea_record_evidence_batch.add_argument("--limit", type=int, default=10)
    idea_record_evidence_batch.add_argument("--provider", choices=["auto", "semantic_scholar", "openalex"], default="auto")
    add_json_args(idea_record_evidence_batch)
    idea_record_evidence_batch.set_defaults(func=cmd_idea_record_evidence_batch)
    idea_finalize = idea_sub.add_parser("finalize")
    idea_finalize.add_argument("--run-id")
    idea_finalize.add_argument("--idea-id")
    idea_finalize.set_defaults(func=cmd_idea_finalize)
    idea_reject = idea_sub.add_parser("reject")
    idea_reject.add_argument("--run-id")
    idea_reject.add_argument("--idea-id")
    idea_reject.add_argument("--reason", required=True)
    idea_reject.set_defaults(func=cmd_idea_reject)
    idea_exhaust = idea_sub.add_parser("exhaust")
    idea_exhaust.add_argument("--run-id")
    idea_exhaust.add_argument("--idea-id")
    idea_exhaust.add_argument("--reason", default="reflection_budget_exhausted")
    idea_exhaust.set_defaults(func=cmd_idea_exhaust)

    node = sub.add_parser("node")
    node_sub = node.add_subparsers(dest="command", required=True)
    transition = node_sub.add_parser("transition")
    transition.add_argument("--run-id")
    transition.add_argument("--node-id", required=True)
    transition.add_argument("--status", required=True)
    transition.add_argument("--reason")
    add_json_args(transition)
    transition.set_defaults(func=cmd_node_transition)

    plan_start = node_sub.add_parser("plan-start")
    plan_start.add_argument("--run-id")
    plan_start.add_argument("--node-id", required=True)
    plan_start.add_argument("--plan-id")
    add_json_args(plan_start)
    plan_start.set_defaults(func=cmd_node_plan_start)
    plan_complete = node_sub.add_parser("plan-complete")
    plan_complete.add_argument("--run-id")
    plan_complete.add_argument("--plan-id", required=True)
    add_json_args(plan_complete)
    plan_complete.set_defaults(func=cmd_node_plan_complete)
    step_start = node_sub.add_parser("step-start")
    step_start.add_argument("--run-id")
    step_start.add_argument("--node-id", required=True)
    step_start.add_argument("--step-id")
    step_start.add_argument("--step-index", type=int)
    step_start.set_defaults(func=cmd_node_step_start)
    step_complete = node_sub.add_parser("step-complete")
    step_complete.add_argument("--run-id")
    step_complete.add_argument("--step-id", required=True)
    step_complete.add_argument("--reason")
    add_json_args(step_complete)
    step_complete.set_defaults(func=cmd_node_step_complete)
    revision_start = node_sub.add_parser("revision-start")
    revision_start.add_argument("--run-id")
    revision_start.add_argument("--node-id", required=True)
    revision_start.add_argument("--revision-id")
    add_json_args(revision_start)
    revision_start.set_defaults(func=cmd_node_revision_start)
    revision_complete = node_sub.add_parser("revision-complete")
    revision_complete.add_argument("--run-id")
    revision_complete.add_argument("--revision-id", required=True)
    add_json_args(revision_complete)
    revision_complete.set_defaults(func=cmd_node_revision_complete)
    revision_critic_start = node_sub.add_parser("revision-critic-start")
    revision_critic_start.add_argument("--run-id")
    revision_critic_start.add_argument("--revision-id", required=True)
    revision_critic_start.add_argument("--critic-id")
    revision_critic_start.set_defaults(func=cmd_node_revision_critic_start)
    revision_critic_complete = node_sub.add_parser("revision-critic-complete")
    revision_critic_complete.add_argument("--run-id")
    revision_critic_complete.add_argument("--critic-id", required=True)
    add_json_args(revision_critic_complete)
    revision_critic_complete.set_defaults(func=cmd_node_revision_critic_complete)
    branch = node_sub.add_parser("branch")
    branch.add_argument("--run-id")
    branch.add_argument("--node-id", required=True)
    branch.add_argument("--from-node")
    branch.add_argument("--revision-id")
    branch.add_argument("--alternative-id")
    branch.add_argument("--reason")
    add_json_args(branch)
    branch.set_defaults(func=cmd_node_branch)
    critic_start = node_sub.add_parser("critic-start")
    critic_start.add_argument("--run-id")
    critic_start.add_argument("--node-id", required=True)
    critic_start.add_argument("--critic-id")
    critic_start.add_argument("--role", choices=sorted(CRITIC_ROLES))
    critic_start.set_defaults(func=cmd_node_critic_start)
    critic_spawn = node_sub.add_parser("critic-spawn-record")
    critic_spawn.add_argument("--run-id")
    critic_spawn.add_argument("--critic-id", required=True)
    critic_spawn.add_argument("--agent-id", required=True)
    critic_spawn.add_argument("--model", required=True)
    critic_spawn.add_argument("--reasoning-effort", required=True)
    critic_spawn.set_defaults(func=cmd_node_critic_spawn_record)
    critic_complete = node_sub.add_parser("critic-complete")
    critic_complete.add_argument("--run-id")
    critic_complete.add_argument("--critic-id", required=True)
    add_json_args(critic_complete)
    critic_complete.set_defaults(func=cmd_node_critic_complete)
    create_workspace = node_sub.add_parser("create-workspace")
    create_workspace.add_argument("--run-id")
    create_workspace.add_argument("--node-id", required=True)
    create_workspace.add_argument("--reason")
    create_workspace.set_defaults(func=cmd_node_create_workspace)
    repair_start = node_sub.add_parser("repair-start")
    repair_start.add_argument("--run-id")
    repair_start.add_argument("--node-id", required=True)
    repair_start.add_argument("--reason")
    repair_start.add_argument("--required-revision", action="append")
    repair_start.set_defaults(func=cmd_node_repair_start)
    repair_complete = node_sub.add_parser("repair-complete")
    repair_complete.add_argument("--run-id")
    repair_complete.add_argument("--repair-id", required=True)
    add_json_args(repair_complete)
    repair_complete.set_defaults(func=cmd_node_repair_complete)

    subagent = sub.add_parser("subagent")
    subagent_sub = subagent.add_subparsers(dest="command", required=True)
    update = subagent_sub.add_parser("update")
    update.add_argument("--run-id")
    update.add_argument("--subagent-id", required=True)
    update.add_argument("--status", required=True)
    update.add_argument("--node-id")
    add_json_args(update)
    update.set_defaults(func=cmd_subagent_update)

    selection = sub.add_parser("selection")
    selection_sub = selection.add_subparsers(dest="command", required=True)
    finalize = selection_sub.add_parser("finalize")
    finalize.add_argument("--run-id")
    finalize.add_argument("--selected-node")
    add_json_args(finalize)
    finalize.set_defaults(func=cmd_selection_finalize)

    finding = sub.add_parser("finding")
    finding_sub = finding.add_subparsers(dest="command", required=True)
    finding_record = finding_sub.add_parser("record")
    finding_record.add_argument("--run-id")
    finding_record.add_argument("--node-id")
    finding_record.add_argument("--kind", choices=sorted(FINDING_KINDS))
    finding_record.add_argument("--summary")
    finding_record.add_argument("--source-ref")
    finding_record.add_argument("--transferable", action="store_true")
    add_json_args(finding_record)
    finding_record.set_defaults(func=cmd_finding_record)

    validation = sub.add_parser("validation")
    validation_sub = validation.add_subparsers(dest="command", required=True)
    validation_record = validation_sub.add_parser("record")
    validation_record.add_argument("--run-id")
    validation_record.add_argument("--gate", required=True)
    validation_record.add_argument("--exit-code", type=int, required=True)
    validation_record.add_argument("--command")
    validation_record.set_defaults(func=cmd_validation_record)

    handoff = sub.add_parser("handoff")
    handoff_sub = handoff.add_subparsers(dest="command", required=True)
    handoff_record = handoff_sub.add_parser("record")
    handoff_record.add_argument("--run-id")
    handoff_record.add_argument("--gate", required=True)
    handoff_record.add_argument("--exit-code", type=int, default=0)
    handoff_record.add_argument("--approved", action="store_true")
    handoff_record.add_argument("--reason")
    handoff_record.set_defaults(func=cmd_handoff_record)

    workspace = sub.add_parser("workspace")
    workspace_sub = workspace.add_subparsers(dest="command", required=True)
    workspace_init = workspace_sub.add_parser("init")
    workspace_init.add_argument("--run-id")
    workspace_init.add_argument("--source", default=".")
    workspace_init.set_defaults(func=cmd_workspace_init)

    resource = sub.add_parser("resource")
    resource_sub = resource.add_subparsers(dest="command", required=True)
    resource_run = resource_sub.add_parser("run")
    resource_run.add_argument("--run-id")
    resource_run.add_argument("--node-id", required=True)
    resource_run.add_argument("--trial-id", required=True)
    resource_run.add_argument("--purpose", default="benchmark")
    resource_run.add_argument("--cwd")
    resource_run.add_argument("--env-json")
    resource_run.add_argument("--metrics-path")
    resource_run.add_argument("--metrics-json")
    resource_run.add_argument("--seed")
    resource_run.add_argument("--benchmark-contract-version", default="v1")
    resource_run.add_argument("--notes", default="")
    resource_run.add_argument("--gpu", action="store_true")
    resource_run.add_argument("command", nargs=argparse.REMAINDER)
    resource_run.set_defaults(func=cmd_resource_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - helper CLI reports structured failures.
        return response("error", error=str(exc), error_type=exc.__class__.__name__)


if __name__ == "__main__":
    raise SystemExit(main())

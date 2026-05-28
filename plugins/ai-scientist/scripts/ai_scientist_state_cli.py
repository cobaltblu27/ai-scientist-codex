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

MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
NODE_STATUSES = {"planned", "implementing", "running", "buggy", "repairing", "candidate", "validating", "accepted", "invalid", "rejected"}
NODE_TERMINAL_STATUSES = {"accepted", "invalid", "rejected"}
CRITIC_VERDICTS = {"ACCEPT", "REVISE", "INVALID", "REJECT"}
CRITIC_STATUS_BY_VERDICT = {"ACCEPT": "accepted", "REVISE": "candidate", "INVALID": "invalid", "REJECT": "rejected"}
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

RESEARCH_NODE_CRITIC_PROMPTS = {
    "scientist": (
        "You are an independent research-node critic in scientist mode. Review node {node_id} for novelty, evidence, ablations, leakage/split integrity, "
        "reproducibility, and publishability. Partial success, promising progress, or evidence needing validation must be REVISE/candidate, not ACCEPT."
    ),
    "researcher": (
        "You are an independent research-node critic in researcher mode. Review node {node_id} for research usefulness, evidence quality, ablations, leakage/split "
        "integrity, reproducibility, and publishability. Partial success, promising progress, or evidence needing validation must be REVISE/candidate, not ACCEPT."
    ),
    "balanced": (
        "You are an independent research-node critic in balanced mode. Review node {node_id} for benchmark integrity, evidence, implementation quality, leakage/split "
        "integrity, reproducibility, practical value, and risk. Partial success, promising progress, or evidence needing validation must be REVISE/candidate, not ACCEPT."
    ),
    "engineer": (
        "You are an independent research-node critic in engineer mode. Review node {node_id} for benchmark integrity, implementation quality, performance, "
        "maintainability, reproducibility, and risk. Partial success, promising progress, or evidence needing validation must be REVISE/candidate, not ACCEPT."
    ),
    "builder": (
        "You are an independent research-node critic in builder mode. Review node {node_id} for benchmark integrity, implementation quality, performance, "
        "maintainability, reproducibility, buildability, and risk. Partial success, promising progress, or evidence needing validation must be REVISE/candidate, not ACCEPT."
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


def research_concurrency_config(payload: dict[str, Any], max_subagents: int, source: str) -> dict[str, Any]:
    research = dict(payload.get("research") if isinstance(payload.get("research"), dict) else {})
    concurrency = dict(research.get("concurrency") if isinstance(research.get("concurrency"), dict) else {})
    concurrency["max_subagents"] = max_subagents
    concurrency["source"] = source
    research["concurrency"] = concurrency
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


def default_config(target: Path, run_id: str, strictness_mode: str, payload: dict[str, Any], *, max_subagents: int | None = None) -> dict[str, Any]:
    if strictness_mode not in MODES:
        raise CliError(f"invalid strictness mode: {strictness_mode}")
    resolved_max, concurrency_source = resolve_research_max_subagents(target, payload, max_subagents)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "target_repo": str(target),
        "strictness_mode": strictness_mode,
        "research": research_concurrency_config(payload, resolved_max, concurrency_source),
        "api_budgets": payload.get("api_budgets", {"semantic_scholar": {"max_calls": 100}}),
        "workspace": payload.get("workspace", {"mode": "copy", "baseline_workspace": f".ai-scientist/runs/{run_id}/baseline-workspace"}),
        "dependency_plan": payload.get("dependency_plan", {"mode": "frozen", "planned_dependencies": []}),
        "benchmark_contract": payload.get("benchmark_contract", {"version": "v1", "command": payload.get("benchmark_command")}),
        "resources": payload.get("resources", {"gpu": {"mode": "single_full_device_when_requested"}}),
        "selection": payload.get("selection", {"good_enough_score_threshold": 75}),
        "created_at": utc_now(),
    }


def cmd_research_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    payload = load_payload(args)
    run_id = args.run_id
    cfg = default_config(target, run_id, args.strictness_mode, payload, max_subagents=args.max_subagents)
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
    return response("ok", run_id=run_id, state_path=str(run_dir(target, run_id) / "loop-state.json"), config_path=str(config_path(target, run_id)))


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
    append_journal_event(target, run_id, "state_transition", details={"command": "research resume", "next_action": next_action})
    set_active_run(target, run_id, str(state.get("phase") or "research"), "active")
    return response("ok", run_id=run_id, next_action=next_action, next_action_details=details)


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


def research_mode_critic_template(config: dict[str, Any]) -> str:
    mode = str(config.get("strictness_mode") or "scientist")
    template = nested_value(config, ["research", "modes", mode, "node_critic_prompt_template"])
    if isinstance(template, str) and template.strip():
        return template
    return RESEARCH_NODE_CRITIC_PROMPTS.get(mode, RESEARCH_NODE_CRITIC_PROMPTS["scientist"])


def build_node_critic_prompt(config: dict[str, Any], node_id: str, critic_id: str, result_path: Path, fingerprint: str) -> str:
    template = research_mode_critic_template(config)
    mode = str(config.get("strictness_mode") or "scientist")
    return (
        template.format(node_id=node_id, mode=mode, critic_id=critic_id, evidence_fingerprint=fingerprint, result_path=str(result_path))
        + "\n\nReturn JSON only to the assigned result_path with this schema:\n"
        '{ "verdict": "ACCEPT|REVISE|INVALID|REJECT", "score": 0-100, "rationale": "...", '
        '"strengths": ["..."], "weaknesses": ["..."], "required_revisions": ["..."], "risk_flags": ["..."] }\n'
        f"Node evidence fingerprint: {fingerprint}\n"
        f"Result path: {result_path}\n"
        "ACCEPT means final evidence is complete and eligible for selection. REVISE means meaningful progress or partial success remains candidate. "
        "INVALID means the evidence cannot be trusted. REJECT means it is not worth continuing or not selected."
    )


def validate_critic_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
        node.update(
            {
                "critic_ref": critic_record["critic_ref"],
                "critic_id": critic_record["critic_id"],
                "critic_verdict": critic_record["verdict"],
                "critic_completed_at": critic_record["completed_at"],
                "critic_evidence_fingerprint": critic_record["evidence_fingerprint"],
                "critic_result_path": critic_record["critic_result_path"],
            }
        )
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
            current.update(
                {
                    "critic_ref": critic_record["critic_ref"],
                    "critic_id": critic_record["critic_id"],
                    "critic_verdict": critic_record["verdict"],
                    "critic_completed_at": critic_record["completed_at"],
                    "critic_evidence_fingerprint": critic_record["evidence_fingerprint"],
                    "critic_result_path": critic_record["critic_result_path"],
                    "node_evidence_fingerprint": critic_record["evidence_fingerprint"],
                }
            )
        if reason:
            key = "rejection_reason" if status in {"rejected", "invalid"} else "reason"
            current[key] = reason
        if status == "accepted":
            phase_state.setdefault("selection", {}).setdefault("status", "pending")

    mutate_loop_state(target, run_id, "state_transition", {"command": "node transition", "status": status, "reason": reason}, mutator, node_id=node_id)
    return node, pending_path


def cmd_node_transition(args: argparse.Namespace) -> int:
    if args.status not in NODE_STATUSES:
        raise CliError(f"invalid node status: {args.status}")
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    node = read_node(target, run_id, args.node_id)
    pending_path = Path(node["result_path"]) if isinstance(node.get("result_path"), str) else research_pending_path(target, run_id, "nodes", args.node_id)
    payload = load_payload_or_path(args, pending_path)
    if args.status in NODE_TERMINAL_STATUSES:
        raise CliError(f"terminal node status {args.status} requires node critic-complete")
    apply_node_status(target, run_id, args.node_id, args.status, payload, reason=args.reason)
    return response("ok", run_id=run_id, node_id=args.node_id, node_status=args.status, node_path=str(node_json_path(target, run_id, args.node_id)), result_path=str(pending_path))


def cmd_node_critic_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    cfg = load_json_if_exists(config_path(target, run_id))
    if not isinstance(cfg, dict):
        raise CliError(f"missing config.json for run {run_id}")
    node = read_node(target, run_id, args.node_id)
    fingerprint = node_evidence_fingerprint(node)
    critic_id = args.critic_id or f"critic-{args.node_id}-{uuid.uuid4().hex[:12]}"
    result_path = research_pending_path(target, run_id, "critics", critic_id)
    ensure_pending_file(result_path)
    prompt = build_node_critic_prompt(cfg, args.node_id, critic_id, result_path, fingerprint)
    pending = {
        "critic_id": critic_id,
        "node_id": args.node_id,
        "status": "pending",
        "started_at": utc_now(),
        "result_path": str(result_path),
        "evidence_fingerprint": fingerprint,
        "prompt": prompt,
    }

    def mutator(new_state: dict[str, Any]) -> None:
        phase_state = new_state.setdefault("state", {})
        pending_critics = phase_state.setdefault("pending_critics", {})
        if critic_id in pending_critics:
            raise CliError(f"critic already exists: {critic_id}")
        pending_critics[critic_id] = pending

    mutate_loop_state(target, run_id, "critic_event", {"command": "node critic-start", "critic_id": critic_id}, mutator, node_id=args.node_id)
    return response("ok", run_id=run_id, node_id=args.node_id, critic_id=critic_id, result_path=str(result_path), evidence_fingerprint=fingerprint, prompt=prompt)


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
    payload = load_payload_or_path(args, result_path)
    if not payload:
        raise CliError(f"critic result payload is required at {result_path}")
    critic = validate_critic_payload(payload)
    node = read_node(target, run_id, node_id)
    fingerprint = node_evidence_fingerprint(node)
    expected = pending.get("evidence_fingerprint")
    if fingerprint != expected:
        raise CliError(f"critic result is stale for node evidence: expected {expected}, found {fingerprint}")
    verdict = str(critic["verdict"])
    status = CRITIC_STATUS_BY_VERDICT[verdict]
    completed_at = utc_now()
    log_path = critic_log_path(target, run_id, args.critic_id)
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "critic_id": args.critic_id,
        "node_id": node_id,
        "verdict": verdict,
        "status": status,
        "critic": critic,
        "evidence_fingerprint": fingerprint,
        "critic_result_path": str(result_path),
        "started_at": pending.get("started_at"),
        "completed_at": completed_at,
    }
    atomic_write_json(log_path, record)
    rationale = str(critic.get("rationale") or critic.get("reason") or "")
    if verdict == "REVISE":
        reason = "; ".join(map(str, critic.get("required_revisions") or [])) or rationale
    else:
        reason = rationale
    critic_record = {
        "critic_ref": str(log_path),
        "critic_id": args.critic_id,
        "verdict": verdict,
        "completed_at": completed_at,
        "evidence_fingerprint": fingerprint,
        "critic_result_path": str(result_path),
    }
    apply_node_status(target, run_id, node_id, status, {}, reason=reason, critic_record=critic_record)

    def mutator(new_state: dict[str, Any]) -> None:
        new_pending = new_state.setdefault("state", {}).setdefault("pending_critics", {})
        new_pending.pop(args.critic_id, None)

    mutate_loop_state(target, run_id, "critic_event", {"command": "node critic-complete", "critic_id": args.critic_id, "verdict": verdict, "status": status}, mutator, node_id=node_id)
    append_journal_event(target, run_id, "critic_event", node_id=node_id, details={"command": "node critic-log", "critic_id": args.critic_id, "verdict": verdict, "critic_ref": str(log_path)})
    return response("ok", run_id=run_id, node_id=node_id, critic_id=args.critic_id, verdict=verdict, node_status=status, critic_ref=str(log_path))


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


def cmd_subagent_update(args: argparse.Namespace) -> int:
    if args.status not in SUBAGENT_STATUSES:
        raise CliError(f"invalid subagent status: {args.status}")
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
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


def cmd_selection_finalize(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    if not state:
        raise CliError(f"missing loop-state.json for run {run_id}")
    payload = load_payload(args)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    selected = payload.get("selected_node") or args.selected_node
    if not isinstance(selected, str) or not selected:
        raise CliError("selected_node is required")
    if not isinstance(nodes.get(selected), dict) or nodes[selected].get("status") != "accepted":
        raise CliError("selected node must be accepted in loop-state.json")
    critic_reason = node_fresh_critic_reason(selected, nodes[selected], required_verdict="ACCEPT")
    if critic_reason:
        raise CliError(f"selected node must have fresh ACCEPT critic verdict: {critic_reason}")
    accepted_nodes = [node_id for node_id, node in nodes.items() if isinstance(node, dict) and node.get("status") == "accepted"]
    for node_id in accepted_nodes:
        critic_reason = node_fresh_critic_reason(node_id, nodes[node_id], required_verdict="ACCEPT")
        if critic_reason:
            raise CliError(f"accepted node must have fresh ACCEPT critic verdict: {critic_reason}")
    ranked = payload.get("ranked_nodes") or [{"node_id": node_id} for node_id in accepted_nodes]
    ranked_ids = [item.get("node_id") for item in ranked if isinstance(item, dict)]
    missing = sorted(set(accepted_nodes) - set(ranked_ids))
    if missing:
        raise CliError(f"selection is missing accepted nodes: {', '.join(missing)}")
    selection = {
        "schema_version": 1,
        "run_id": run_id,
        "selection_status": "final",
        "provisional": False,
        "selected_node": selected,
        "ranked_nodes": ranked,
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
    start.add_argument("--strictness-mode", default="scientist")
    start.add_argument("--max-subagents", type=int)
    add_json_args(start)
    start.set_defaults(func=cmd_research_start)
    resume = research_sub.add_parser("resume")
    resume.add_argument("--run-id")
    resume.set_defaults(func=cmd_research_resume)
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
    add_json_args(idea_search)
    idea_search.set_defaults(func=cmd_idea_search_semantic_scholar)
    idea_record_evidence_batch = idea_sub.add_parser("record-evidence-batch")
    idea_record_evidence_batch.add_argument("--run-id")
    idea_record_evidence_batch.add_argument("--idea-ids", nargs="+", required=True)
    idea_record_evidence_batch.add_argument("--queries", nargs="+", required=True)
    idea_record_evidence_batch.add_argument("--limit", type=int, default=10)
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
    critic_start = node_sub.add_parser("critic-start")
    critic_start.add_argument("--run-id")
    critic_start.add_argument("--node-id", required=True)
    critic_start.add_argument("--critic-id")
    critic_start.set_defaults(func=cmd_node_critic_start)
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

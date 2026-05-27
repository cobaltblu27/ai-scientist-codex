#!/usr/bin/env python3
"""Deterministic state helpers for agent-driven AI Scientist ideation.

This module deliberately does not spawn Codex or own an ideation loop. The
current Codex session is the orchestrator; these helpers only persist state,
validate transitions, and compute the next cursor action for the Stop hook.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_scientist_state import (
    ai_root,
    append_journal_event,
    atomic_write_json,
    config_path,
    data_hash,
    has_int_score,
    has_substantive_value,
    load_json_if_exists,
    load_loop_state,
    mutate_loop_state,
    run_dir,
    set_active_run,
    start_phase,
    utc_now,
)

MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
INTENT_ROLES = {"generator", "critic", "ranker"}
TERMINAL_IDEA_STATUSES = {"accepted", "accepted_without_reference", "rejected", "error", "exhausted"}
TERMINAL_IDEATION_STATUSES = {"COMPLETED", "COMPLETED_BUDGET_EXHAUSTED", "EXHAUSTED_NO_CANDIDATE", "CANCELLED"}
SUCCESS_TERMINAL_STATUSES = {"COMPLETED", "COMPLETED_BUDGET_EXHAUSTED"}


DEFAULT_PROMPTS = {
    "idea_generation_prompt_template": (
        "You are an AI Scientist idea-generation subagent running in {mode} mode.\n"
        "Topic: {prompt}\n"
        "Produce one canonical research idea for slot {idea_id}. Return structured JSON only."
    ),
    "critic_prompt_template": (
        "You are a short-lived critic for {mode} mode. Review idea {idea_id} draft {draft_version}.\n"
        "Previous verdict: {previous_verdict}\n"
        "Return verdict, score, strengths, weaknesses, required_revisions, mode_specific_assessment, and risk_flags."
    ),
    "ranking_prompt_template": (
        "Rank terminal ideation candidates for {mode} mode. Score every terminal valid idea and select one default candidate."
    ),
}


DEFAULT_MODE_PRESETS: dict[str, dict[str, Any]] = {
    "scientist": {
        "s2_required": True,
        "allow_accepted_without_reference": False,
        "allow_selection_without_reference": False,
        "candidate_evaluations": ["ACCEPTED"],
        "scoring_weights": {"novelty": 0.35, "evidence": 0.25, "feasibility": 0.20, "repo_fit": 0.20},
        **DEFAULT_PROMPTS,
    },
    "researcher": {
        "s2_required": True,
        "allow_accepted_without_reference": False,
        "allow_selection_without_reference": False,
        "candidate_evaluations": ["ACCEPTED"],
        "scoring_weights": {"novelty": 0.30, "evidence": 0.30, "feasibility": 0.20, "repo_fit": 0.20},
        **DEFAULT_PROMPTS,
    },
    "balanced": {
        "s2_required": True,
        "allow_accepted_without_reference": True,
        "allow_selection_without_reference": True,
        "candidate_evaluations": ["ACCEPTED", "ACCEPTED_WITHOUT_REFERENCE"],
        "scoring_weights": {"novelty": 0.25, "evidence": 0.20, "feasibility": 0.30, "repo_fit": 0.25},
        **DEFAULT_PROMPTS,
    },
    "engineer": {
        "s2_required": False,
        "allow_accepted_without_reference": True,
        "allow_selection_without_reference": True,
        "candidate_evaluations": ["ACCEPTED", "ACCEPTED_WITHOUT_REFERENCE"],
        "scoring_weights": {"performance": 0.45, "feasibility": 0.30, "repo_fit": 0.20, "novelty": 0.05},
        **DEFAULT_PROMPTS,
    },
    "builder": {
        "s2_required": False,
        "allow_accepted_without_reference": True,
        "allow_selection_without_reference": True,
        "candidate_evaluations": ["ACCEPTED", "ACCEPTED_WITHOUT_REFERENCE"],
        "scoring_weights": {"performance": 0.40, "feasibility": 0.35, "repo_fit": 0.20, "novelty": 0.05},
        **DEFAULT_PROMPTS,
    },
}


DEFAULT_IDEATION_CONFIG: dict[str, Any] = {
    "default_mode": "scientist",
    "num_ideas_required": 10,
    "min_candidates_required": 1,
    "reflection_budget": 10,
    "early_stop_allowed": False,
    "modes": DEFAULT_MODE_PRESETS,
}


class IdeationStateError(Exception):
    pass


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_ideas_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "ideas.json"


def run_logs_dir(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "logs"


def load_payload_from_args(json_value: str | None = None, path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        payload = json.loads(path.read_text())
    elif json_value:
        payload = json.loads(json_value)
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise IdeationStateError("payload must be a JSON object")
    return payload


def load_plugin_config() -> dict[str, Any]:
    path = plugin_root() / "config" / "config.json"
    value = load_json_if_exists(path)
    return value if isinstance(value, dict) else {}


def load_project_override(target_repo: Path) -> dict[str, Any]:
    value = load_json_if_exists(ai_root(target_repo) / "config.json")
    return value if isinstance(value, dict) else {}


def choose_mode(config: dict[str, Any], requested_mode: str | None) -> str:
    ideation = config.get("ideation") if isinstance(config.get("ideation"), dict) else {}
    mode = requested_mode or config.get("strictness_mode") or ideation.get("default_mode") or "scientist"
    if mode not in MODES:
        raise IdeationStateError(f"invalid ideation mode: {mode}")
    return str(mode)


def validate_mode_preset(config: dict[str, Any], mode: str) -> dict[str, Any]:
    ideation = config.get("ideation") if isinstance(config.get("ideation"), dict) else {}
    modes = ideation.get("modes") if isinstance(ideation.get("modes"), dict) else {}
    preset = modes.get(mode)
    if not isinstance(preset, dict):
        raise IdeationStateError(f"missing ideation preset for mode: {mode}")
    for key in ("idea_generation_prompt_template", "critic_prompt_template", "ranking_prompt_template"):
        if not isinstance(preset.get(key), str) or not preset[key].strip():
            raise IdeationStateError(f"ideation preset {mode} missing {key}")
    return preset


def frozen_config(
    target_repo: Path,
    run_id: str,
    requested_mode: str | None,
    *,
    num_ideas_required: int | None = None,
    min_candidates_required: int | None = None,
    reflection_budget: int | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "ideation": DEFAULT_IDEATION_CONFIG,
        "api_budgets": {"semantic_scholar": {"max_calls": 100, "max_results_per_query": 10}},
        "workspace": {"mode": "copy"},
        "dependency_plan": {"mode": "frozen", "planned_dependencies": []},
        "benchmark_contract": {"version": "ideation-v1", "command": None},
        "resources": {"gpu": {"mode": "not_applicable_ideation"}},
        "selection": {"good_enough_score_threshold": 75},
    }
    merged = deep_merge(base, load_plugin_config())
    merged = deep_merge(merged, load_project_override(target_repo))
    mode = choose_mode(merged, requested_mode)
    ideation_cfg = merged.setdefault("ideation", {})
    if num_ideas_required is not None:
        ideation_cfg["num_ideas_required"] = num_ideas_required
    if min_candidates_required is not None:
        ideation_cfg["min_candidates_required"] = min_candidates_required
    if reflection_budget is not None:
        ideation_cfg["reflection_budget"] = reflection_budget
    validate_mode_preset(merged, mode)
    merged.update(
        {
            "schema_version": 1,
            "run_id": run_id,
            "target_repo": str(target_repo.resolve()),
            "strictness_mode": mode,
            "created_at": utc_now(),
        }
    )
    return merged


def mode_preset(config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("strictness_mode") or "scientist")
    return validate_mode_preset(config, mode)


def idea_states(state: dict[str, Any]) -> dict[str, Any]:
    phase_state = state.setdefault("state", {})
    ideas = phase_state.setdefault("idea_states", {})
    if not isinstance(ideas, dict):
        raise IdeationStateError("loop-state.json state.idea_states must be an object")
    return ideas


def current_config(target_repo: Path, run_id: str) -> dict[str, Any]:
    cfg = load_json_if_exists(config_path(target_repo, run_id))
    if not isinstance(cfg, dict):
        raise IdeationStateError(f"missing run config.json for ideation run {run_id}")
    return cfg


def terminal_ideas(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    for idea in idea_states(state).values():
        if isinstance(idea, dict) and str(idea.get("status") or "") in TERMINAL_IDEA_STATUSES:
            values.append(idea)
    return sorted(values, key=lambda item: int(item.get("slot_index") or 0))


def is_researchable_idea(idea: dict[str, Any], config: dict[str, Any]) -> bool:
    evaluation = str(idea.get("evaluation") or "").upper()
    if evaluation == "ACCEPTED":
        return True
    if evaluation == "ACCEPTED_WITHOUT_REFERENCE":
        return bool(mode_preset(config).get("allow_selection_without_reference"))
    return False


def researchable_candidates(state: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    return [idea for idea in terminal_ideas(state) if is_researchable_idea(idea, config)]


def has_literature_evidence(idea: dict[str, Any]) -> bool:
    evidence = idea.get("literature_evidence")
    if isinstance(evidence, list) and evidence:
        return True
    if isinstance(evidence, dict) and evidence:
        return True
    return int(idea.get("literature_search_count") or 0) > 0


def latest_critic_matches(idea: dict[str, Any]) -> bool:
    critic = idea.get("latest_critic")
    if not isinstance(critic, dict):
        return False
    return (
        critic.get("draft_version") == idea.get("draft_version")
        and critic.get("idea_hash") == idea.get("idea_hash")
    )


def reflection_budget_exhausted(phase_state: dict[str, Any]) -> bool:
    budget = int(phase_state.get("reflection_budget") or 0)
    return budget > 0 and int(phase_state.get("iterations_used") or 0) >= budget


def next_idea_id(phase_state: dict[str, Any]) -> str:
    return f"idea-{int(phase_state.get('attempted_slots') or 0) + 1:03d}"


def cursor_for_state(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    if state.get("phase") != "ideation":
        return {"next_action": None, "next_action_details": {"reason": "not ideation"}}
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    if state.get("active") is not True:
        return {"next_action": None, "next_action_details": {"reason": f"terminal:{state.get('phase_status')}"}}
    pending = phase_state.get("pending_intent")
    if isinstance(pending, dict):
        return {
            "next_action": "record_subagent_result",
            "next_action_details": {
                "reason": "subagent intent is pending",
                "intent_id": pending.get("intent_id"),
                "role": pending.get("role"),
                "idea_id": pending.get("idea_id"),
            },
        }
    cfg = config or {}
    preset = mode_preset(cfg) if cfg else DEFAULT_MODE_PRESETS["scientist"]
    ideas = phase_state.get("idea_states") if isinstance(phase_state.get("idea_states"), dict) else {}
    active_id = phase_state.get("active_idea_id")
    if isinstance(active_id, str) and active_id:
        idea = ideas.get(active_id)
        if not isinstance(idea, dict):
            return {"next_action": "start_next_idea", "next_action_details": {"reason": "active idea missing state", "idea_id": active_id}}
        status = str(idea.get("status") or "")
        if status in {"generating", "critic_running", "ranking_running"}:
            return {"next_action": "record_subagent_result", "next_action_details": {"reason": f"{status} has no recorded result", "idea_id": active_id}}
        if not isinstance(idea.get("latest_draft"), dict):
            return {"next_action": "start_next_idea", "next_action_details": {"reason": "active idea has no draft", "idea_id": active_id}}
        if preset.get("s2_required") and not has_literature_evidence(idea):
            return {"next_action": "search_semantic_scholar", "next_action_details": {"reason": "mode requires literature evidence", "idea_id": active_id}}
        if not latest_critic_matches(idea):
            return {"next_action": "spawn_critic", "next_action_details": {"reason": "latest draft needs fresh critic", "idea_id": active_id, "draft_version": idea.get("draft_version")}}
        verdict = str(idea["latest_critic"].get("verdict") or "").upper()
        if verdict in {"REVISE", "REJECT"}:
            return {"next_action": "revise_or_reject", "next_action_details": {"reason": f"critic verdict {verdict}", "idea_id": active_id}}
        return {"next_action": "finalize_idea", "next_action_details": {"reason": f"critic verdict {verdict}", "idea_id": active_id}}
    required = int(phase_state.get("num_ideas_required") or 0)
    attempted = int(phase_state.get("attempted_slots") or 0)
    early_stop = bool(phase_state.get("early_stop_allowed"))
    candidates = researchable_candidates(state, cfg) if cfg else []
    if attempted < required and not reflection_budget_exhausted(phase_state) and not (early_stop and candidates):
        return {"next_action": "start_next_idea", "next_action_details": {"reason": "idea slots remain", "next_idea_id": next_idea_id(phase_state)}}
    ranking = phase_state.get("ranking") if isinstance(phase_state.get("ranking"), dict) else {}
    if candidates and ranking.get("status") != "final":
        return {"next_action": "rank_candidates", "next_action_details": {"reason": "researchable candidates need ranking", "candidate_count": len(candidates)}}
    return {"next_action": "complete_or_exhaust", "next_action_details": {"reason": "slots or budget exhausted", "candidate_count": len(candidates)}}


def update_cursor(state: dict[str, Any], config: dict[str, Any] | None = None) -> None:
    cursor = cursor_for_state(state, config)
    phase_state = state.setdefault("state", {})
    orchestrator = phase_state.setdefault("orchestrator", {})
    orchestrator["next_action"] = cursor.get("next_action")
    orchestrator["next_action_details"] = cursor.get("next_action_details") or {}
    orchestrator["last_checkpoint_at"] = utc_now()


def public_idea_record(idea: dict[str, Any]) -> dict[str, Any]:
    latest_draft = idea.get("latest_draft") if isinstance(idea.get("latest_draft"), dict) else {}
    return {
        "id": idea.get("id"),
        "status": idea.get("status"),
        "evaluation": idea.get("evaluation"),
        "rank": idea.get("rank"),
        "score": idea.get("score"),
        "score_components": idea.get("score_components"),
        "rationale": idea.get("rationale"),
        "risk_flags": idea.get("risk_flags"),
        "selected": idea.get("selected") is True,
        "researchable": idea.get("researchable") is True,
        "source_run_id": idea.get("source_run_id"),
        "reflection_count": int(idea.get("reflection_count") or 0),
        "literature_search_count": int(idea.get("literature_search_count") or 0),
        "draft_version": idea.get("draft_version"),
        "idea_hash": idea.get("idea_hash"),
        "manual_selection_only": idea.get("manual_selection_only"),
        "normalized": latest_draft,
        "upstream": latest_draft.get("upstream") if isinstance(latest_draft.get("upstream"), dict) else latest_draft,
    }


def sync_ideas_archive(target_repo: Path, run_id: str, state: dict[str, Any]) -> None:
    records = [public_idea_record(idea) for idea in terminal_ideas(state)]
    atomic_write_json(run_ideas_path(target_repo, run_id), {"schema_version": 1, "run_id": run_id, "ideas": records, "updated_at": utc_now()})


def write_payload_log(target_repo: Path, run_id: str, subdir: str, filename: str, payload: dict[str, Any]) -> Path:
    path = run_logs_dir(target_repo, run_id) / subdir / filename
    atomic_write_json(path, payload)
    return path


def increment_iteration(phase_state: dict[str, Any]) -> None:
    phase_state["iterations_used"] = int(phase_state.get("iterations_used") or 0) + 1


def ensure_active_ideation_state(target_repo: Path, run_id: str) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not isinstance(state, dict):
        raise IdeationStateError(f"missing loop-state.json for run {run_id}")
    if state.get("phase") != "ideation":
        raise IdeationStateError(f"run {run_id} is not an ideation run")
    return state


def start_ideation(
    target_repo: Path,
    run_id: str,
    prompt: str,
    *,
    mode: str | None = None,
    num_ideas_required: int | None = None,
    min_candidates_required: int | None = None,
    reflection_budget: int | None = None,
) -> dict[str, Any]:
    if load_loop_state(target_repo, run_id):
        raise IdeationStateError(f"ideation run already exists: {run_id}")
    if not prompt.strip():
        raise IdeationStateError("ideation prompt is required")
    cfg = frozen_config(
        target_repo,
        run_id,
        mode,
        num_ideas_required=num_ideas_required,
        min_candidates_required=min_candidates_required,
        reflection_budget=reflection_budget,
    )
    ideation_cfg = cfg["ideation"]
    initial = {
        "prompt": prompt,
        "mode": cfg["strictness_mode"],
        "orchestrator": {"role": "main_codex_session", "iteration": 0},
        "num_ideas_required": int(ideation_cfg.get("num_ideas_required") or 10),
        "min_candidates_required": int(ideation_cfg.get("min_candidates_required") or 1),
        "reflection_budget": int(ideation_cfg.get("reflection_budget") or 10),
        "early_stop_allowed": bool(ideation_cfg.get("early_stop_allowed")),
        "attempted_slots": 0,
        "iterations_used": 0,
        "active_idea_id": None,
        "pending_intent": None,
        "intents": {},
        "idea_states": {},
        "ranking": {"status": "pending"},
        "handoff": {"status": "pending", "candidates": [], "selected_idea_id": None},
    }
    state = start_phase(target_repo, run_id, "ideation", initial)
    update_cursor(state, cfg)
    atomic_write_json(config_path(target_repo, run_id), cfg)
    atomic_write_json(run_ideas_path(target_repo, run_id), {"schema_version": 1, "run_id": run_id, "ideas": [], "updated_at": utc_now()})
    atomic_write_json(run_dir(target_repo, run_id) / "loop-state.json", state)
    append_journal_event(target_repo, run_id, "state_transition", details={"command": "ideation start", "prompt": prompt, "mode": cfg["strictness_mode"], "state_hash": data_hash(state)})
    return state


def resume_ideation(target_repo: Path, run_id: str, *, prompt: bool = False) -> dict[str, Any]:
    state = ensure_active_ideation_state(target_repo, run_id)
    cfg = current_config(target_repo, run_id)
    update_cursor(state, cfg)
    atomic_write_json(run_dir(target_repo, run_id) / "loop-state.json", state)
    cursor = cursor_for_state(state, cfg)
    append_journal_event(target_repo, run_id, "state_transition", details={"command": "ideation resume", **cursor})
    response = {"run_id": run_id, **cursor, "phase_status": state.get("phase_status")}
    if prompt:
        response["prompt"] = orchestration_prompt(state, cfg, cursor)
    return response


def orchestration_prompt(state: dict[str, Any], config: dict[str, Any], cursor: dict[str, Any]) -> str:
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    preset = mode_preset(config)
    next_action = cursor.get("next_action")
    lines = [
        "You are the main Codex ideation orchestrator for AI Scientist.",
        "Do not run a Python ideation orchestrator or nested codex exec.",
        f"Run id: {state.get('run_id')}",
        f"Mode: {config.get('strictness_mode')}",
        f"Next action: {next_action}",
        f"Details: {json.dumps(cursor.get('next_action_details') or {}, sort_keys=True)}",
    ]
    if next_action == "start_next_idea":
        lines.append(preset["idea_generation_prompt_template"])
    elif next_action == "spawn_critic":
        lines.append(preset["critic_prompt_template"])
    elif next_action == "rank_candidates":
        lines.append(preset["ranking_prompt_template"])
    lines.append(f"Original topic: {phase_state.get('prompt')}")
    return "\n".join(lines)


def allocate_idea_if_needed(phase_state: dict[str, Any], idea_id: str | None = None) -> str:
    ideas = phase_state.setdefault("idea_states", {})
    if idea_id:
        if idea_id not in ideas:
            phase_state["attempted_slots"] = int(phase_state.get("attempted_slots") or 0) + 1
            ideas[idea_id] = {"id": idea_id, "slot_index": int(phase_state["attempted_slots"]), "status": "generating"}
        phase_state["active_idea_id"] = idea_id
        return idea_id
    active_id = phase_state.get("active_idea_id")
    if isinstance(active_id, str) and active_id:
        return active_id
    required = int(phase_state.get("num_ideas_required") or 0)
    attempted = int(phase_state.get("attempted_slots") or 0)
    if attempted >= required:
        raise IdeationStateError("no idea slots remain")
    new_id = next_idea_id(phase_state)
    phase_state["attempted_slots"] = attempted + 1
    ideas[new_id] = {"id": new_id, "slot_index": phase_state["attempted_slots"], "status": "generating", "source_run_id": None}
    phase_state["active_idea_id"] = new_id
    return new_id


def start_intent(target_repo: Path, run_id: str, role: str, *, idea_id: str | None = None) -> dict[str, Any]:
    if role not in INTENT_ROLES:
        raise IdeationStateError(f"invalid intent role: {role}")
    cfg = current_config(target_repo, run_id)
    intent_holder: dict[str, Any] = {}

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        if isinstance(phase_state.get("pending_intent"), dict):
            raise IdeationStateError("a subagent intent is already pending")
        resolved_idea_id = idea_id
        draft_version = None
        idea_hash = None
        if role in {"generator", "critic"}:
            resolved_idea_id = allocate_idea_if_needed(phase_state, idea_id)
        ideas = phase_state.setdefault("idea_states", {})
        if role == "critic":
            idea = ideas.get(resolved_idea_id)
            if not isinstance(idea, dict) or not isinstance(idea.get("latest_draft"), dict):
                raise IdeationStateError("critic intent requires an existing latest draft")
            draft_version = idea.get("draft_version")
            idea_hash = idea.get("idea_hash")
            idea["status"] = "critic_running"
        elif role == "generator":
            ideas[resolved_idea_id]["status"] = "generating"
        elif role == "ranker":
            candidates = researchable_candidates(state, cfg)
            if not candidates:
                raise IdeationStateError("ranker intent requires at least one researchable candidate")
        intent_id = f"intent-{len(phase_state.setdefault('intents', {})) + 1:03d}"
        intent = {
            "intent_id": intent_id,
            "role": role,
            "idea_id": resolved_idea_id,
            "draft_version": draft_version,
            "idea_hash": idea_hash,
            "status": "running",
            "started_at": utc_now(),
        }
        phase_state["pending_intent"] = intent
        phase_state["intents"][intent_id] = intent
        intent_holder.update(intent)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "subagent_event", {"command": "ideation intent start", "role": role, "idea_id": idea_id}, mutator, subagent_id=None)
    sync_ideas_archive(target_repo, run_id, updated)
    return intent_holder


def clear_pending_intent_for_role(phase_state: dict[str, Any], role: str, idea_id: str | None = None) -> None:
    pending = phase_state.get("pending_intent")
    if not isinstance(pending, dict):
        return
    if pending.get("role") != role:
        raise IdeationStateError(f"pending intent role is {pending.get('role')}, not {role}")
    if idea_id and pending.get("idea_id") != idea_id:
        raise IdeationStateError("pending intent idea_id mismatch")
    intent_id = pending.get("intent_id")
    if isinstance(intent_id, str):
        phase_state.setdefault("intents", {}).setdefault(intent_id, {}).update({"status": "completed", "completed_at": utc_now()})
    phase_state["pending_intent"] = None


def complete_intent(target_repo: Path, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    state = ensure_active_ideation_state(target_repo, run_id)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    pending = phase_state.get("pending_intent")
    if not isinstance(pending, dict):
        raise IdeationStateError("no pending subagent intent")
    role = str(pending.get("role") or "")
    if role == "generator":
        idea_payload = payload.get("idea") if isinstance(payload.get("idea"), dict) else payload
        return record_draft(target_repo, run_id, idea_payload, idea_id=pending.get("idea_id"))
    if role == "critic":
        verdict_payload = payload.get("critic") if isinstance(payload.get("critic"), dict) else payload
        return record_critic(target_repo, run_id, verdict_payload, idea_id=pending.get("idea_id"))
    if role == "ranker":
        ranking_payload = payload.get("ranking") if isinstance(payload.get("ranking"), dict) else payload
        return finalize_ranking(target_repo, run_id, ranking_payload)
    raise IdeationStateError(f"unknown pending intent role: {role}")


def cancel_intent(target_repo: Path, run_id: str, reason: str) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        pending = phase_state.get("pending_intent")
        if not isinstance(pending, dict):
            raise IdeationStateError("no pending subagent intent")
        pending["status"] = "cancelled"
        pending["reason"] = reason
        pending["completed_at"] = utc_now()
        intent_id = pending.get("intent_id")
        if isinstance(intent_id, str):
            phase_state.setdefault("intents", {}).setdefault(intent_id, {}).update(pending)
        phase_state["pending_intent"] = None
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "subagent_event", {"command": "ideation intent cancel", "reason": reason}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def normalize_idea_payload(payload: dict[str, Any], idea_id: str, run_id: str) -> dict[str, Any]:
    idea = deepcopy(payload)
    idea.setdefault("id", idea_id)
    if idea["id"] != idea_id:
        raise IdeationStateError(f"idea id mismatch: expected {idea_id}, got {idea['id']}")
    if not any(has_substantive_value(idea.get(key)) for key in ("title", "hypothesis", "abstract", "Name", "Title", "Short Hypothesis")):
        raise IdeationStateError("idea draft must include at least a title, hypothesis, abstract, or upstream hypothesis field")
    idea.setdefault("source_run_id", run_id)
    return idea


def record_draft(target_repo: Path, run_id: str, payload: dict[str, Any], *, idea_id: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = allocate_idea_if_needed(phase_state, idea_id)
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.setdefault(resolved_id, {"id": resolved_id})
        normalized = normalize_idea_payload(payload, resolved_id, run_id)
        draft_version = int(idea.get("draft_version") or 0) + 1
        idea_hash = data_hash(normalized)
        draft_ref = write_payload_log(target_repo, run_id, "drafts", f"{resolved_id}-v{draft_version:02d}.json", normalized)
        idea.update(
            {
                "id": resolved_id,
                "source_run_id": run_id,
                "status": "drafted",
                "evaluation": None,
                "latest_draft": normalized,
                "draft_version": draft_version,
                "idea_hash": idea_hash,
                "draft_ref": str(draft_ref),
                "reflection_count": int(idea.get("reflection_count") or 0) + 1,
                "updated_at": utc_now(),
            }
        )
        idea.setdefault("drafts", []).append({"draft_version": draft_version, "idea_hash": idea_hash, "draft_ref": str(draft_ref)})
        idea.pop("latest_critic", None)
        clear_pending_intent_for_role(phase_state, "generator", resolved_id)
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "idea draft", "idea_id": idea_id}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def start_revision(target_repo: Path, run_id: str, idea_id: str, reason: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.get(idea_id)
        if not isinstance(idea, dict):
            raise IdeationStateError(f"unknown idea_id: {idea_id}")
        if str(idea.get("status") or "") in TERMINAL_IDEA_STATUSES:
            raise IdeationStateError("terminal idea cannot be revised")
        phase_state["active_idea_id"] = idea_id
        idea["status"] = "revision_requested"
        idea["revision_reason"] = reason
        idea["updated_at"] = utc_now()
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "idea revise-start", "idea_id": idea_id, "reason": reason}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def validate_critic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    verdict = str(payload.get("verdict") or "").upper()
    if verdict not in {"ACCEPT", "ACCEPT_WITHOUT_REFERENCE", "REVISE", "REJECT"}:
        raise IdeationStateError("critic verdict must be ACCEPT, ACCEPT_WITHOUT_REFERENCE, REVISE, or REJECT")
    score = payload.get("score")
    if not has_int_score(score):
        raise IdeationStateError("critic score must be an integer 0..100")
    critic = deepcopy(payload)
    critic["verdict"] = verdict
    return critic


def record_critic(target_repo: Path, run_id: str, payload: dict[str, Any], *, idea_id: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    critic = validate_critic_payload(payload)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = idea_id or phase_state.get("active_idea_id")
        if not isinstance(resolved_id, str) or not resolved_id:
            raise IdeationStateError("critic-record requires an active idea or --idea-id")
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.get(resolved_id)
        if not isinstance(idea, dict):
            raise IdeationStateError(f"unknown idea_id: {resolved_id}")
        if not isinstance(idea.get("latest_draft"), dict):
            raise IdeationStateError("critic-record requires a latest draft")
        critic["idea_id"] = resolved_id
        critic["draft_version"] = idea.get("draft_version")
        critic["idea_hash"] = idea.get("idea_hash")
        critic["recorded_at"] = utc_now()
        critic_ref = write_payload_log(target_repo, run_id, "critics", f"{resolved_id}-v{int(idea.get('draft_version') or 0):02d}.json", critic)
        critic["critic_ref"] = str(critic_ref)
        idea["latest_critic"] = critic
        idea["score"] = critic["score"]
        verdict = critic["verdict"]
        if verdict == "REVISE":
            idea["status"] = "needs_revision"
        elif verdict == "REJECT":
            idea["status"] = "critic_rejected"
        elif verdict == "ACCEPT_WITHOUT_REFERENCE":
            idea["status"] = "critic_accepted_without_reference"
        else:
            idea["status"] = "critic_accepted"
        idea["updated_at"] = utc_now()
        clear_pending_intent_for_role(phase_state, "critic", resolved_id)
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "critic_event", {"command": "idea critic-record", "idea_id": idea_id, "verdict": critic["verdict"]}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def semantic_scholar_request(query: str, limit: int) -> dict[str, Any]:
    params = urllib.parse.urlencode({"query": query, "limit": str(limit), "fields": "title,year,citationCount,venue,url,authors"})
    request = urllib.request.Request(f"https://api.semanticscholar.org/graph/v1/paper/search?{params}")
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        request.add_header("x-api-key", api_key)
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public API URL.
        return json.loads(response.read().decode("utf-8"))


def record_semantic_scholar_search(
    target_repo: Path,
    run_id: str,
    *,
    idea_id: str | None = None,
    query: str | None = None,
    evidence_payload: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    evidence = evidence_payload or semantic_scholar_request(query or "", limit)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = idea_id or phase_state.get("active_idea_id")
        if not isinstance(resolved_id, str) or not resolved_id:
            raise IdeationStateError("semantic scholar search requires an active idea or --idea-id")
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.get(resolved_id)
        if not isinstance(idea, dict):
            raise IdeationStateError(f"unknown idea_id: {resolved_id}")
        evidence_ref = write_payload_log(target_repo, run_id, "semantic-scholar", f"{resolved_id}-{int(idea.get('literature_search_count') or 0) + 1:02d}.json", evidence)
        idea.setdefault("literature_evidence", []).append({"query": query, "evidence_ref": str(evidence_ref), "result_count": len(evidence.get("data", [])) if isinstance(evidence.get("data"), list) else None})
        idea["literature_search_count"] = int(idea.get("literature_search_count") or 0) + 1
        idea["updated_at"] = utc_now()
        phase_state["s2_query_count"] = int(phase_state.get("s2_query_count") or 0) + 1
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "api_call", {"command": "idea search-semantic-scholar", "idea_id": idea_id, "query": query, "service": "semantic_scholar"}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def finalize_idea(target_repo: Path, run_id: str, *, idea_id: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    preset = mode_preset(cfg)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = idea_id or phase_state.get("active_idea_id")
        if not isinstance(resolved_id, str) or not resolved_id:
            raise IdeationStateError("finalize requires an active idea or --idea-id")
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.get(resolved_id)
        if not isinstance(idea, dict):
            raise IdeationStateError(f"unknown idea_id: {resolved_id}")
        if not latest_critic_matches(idea):
            raise IdeationStateError("critic_stale_for_current_idea")
        critic = idea["latest_critic"]
        verdict = str(critic.get("verdict") or "").upper()
        if verdict == "REVISE":
            raise IdeationStateError("critic requested revision")
        if verdict == "REJECT":
            raise IdeationStateError("critic rejected idea; call idea reject or idea revise-start")
        if verdict == "ACCEPT_WITHOUT_REFERENCE":
            if not preset.get("allow_accepted_without_reference"):
                raise IdeationStateError("mode does not allow ACCEPTED_WITHOUT_REFERENCE")
            evaluation = "ACCEPTED_WITHOUT_REFERENCE"
            status = "accepted_without_reference"
        else:
            if preset.get("s2_required") and not has_literature_evidence(idea):
                if preset.get("allow_accepted_without_reference"):
                    evaluation = "ACCEPTED_WITHOUT_REFERENCE"
                    status = "accepted_without_reference"
                else:
                    raise IdeationStateError("literature_evidence_required")
            else:
                evaluation = "ACCEPTED"
                status = "accepted"
        idea["status"] = status
        idea["evaluation"] = evaluation
        idea["score"] = critic["score"]
        idea["rank"] = None
        idea["manual_selection_only"] = evaluation == "ACCEPTED_WITHOUT_REFERENCE" and not preset.get("allow_selection_without_reference")
        idea["updated_at"] = utc_now()
        phase_state["active_idea_id"] = None
        key = "accepted_without_reference_count" if evaluation == "ACCEPTED_WITHOUT_REFERENCE" else "accepted_count"
        phase_state[key] = int(phase_state.get(key) or 0) + 1
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "idea finalize", "idea_id": idea_id}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def reject_idea(target_repo: Path, run_id: str, *, idea_id: str | None = None, reason: str = "rejected") -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = idea_id or phase_state.get("active_idea_id")
        if not isinstance(resolved_id, str) or not resolved_id:
            raise IdeationStateError("reject requires an active idea or --idea-id")
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.get(resolved_id)
        if not isinstance(idea, dict):
            raise IdeationStateError(f"unknown idea_id: {resolved_id}")
        critic = idea.get("latest_critic") if isinstance(idea.get("latest_critic"), dict) else {}
        idea["status"] = "rejected"
        idea["evaluation"] = "REJECTED"
        idea["rejection_reason"] = reason
        idea["score"] = critic.get("score") if has_int_score(critic.get("score")) else idea.get("score")
        idea["rank"] = None
        idea["updated_at"] = utc_now()
        phase_state["rejected_count"] = int(phase_state.get("rejected_count") or 0) + 1
        if phase_state.get("active_idea_id") == resolved_id:
            phase_state["active_idea_id"] = None
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "idea reject", "idea_id": idea_id, "reason": reason}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def exhaust_idea(target_repo: Path, run_id: str, *, idea_id: str | None = None, reason: str = "reflection_budget_exhausted") -> dict[str, Any]:
    return reject_idea(target_repo, run_id, idea_id=idea_id, reason=reason)


def ranking_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("ranked_ideas") or payload.get("candidates") or payload.get("ideas")
    if not isinstance(items, list) or not items:
        raise IdeationStateError("ranking payload requires ranked_ideas/candidates list")
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise IdeationStateError("ranking items must be objects")
        idea_id = item.get("idea_id") or item.get("id")
        if not isinstance(idea_id, str) or not idea_id:
            raise IdeationStateError("ranking item missing idea_id")
        score = item.get("score")
        if not has_int_score(score):
            raise IdeationStateError(f"ranking item {idea_id} missing integer score 0..100")
        normalized.append({**item, "idea_id": idea_id, "score": score})
    return normalized


def finalize_ranking(target_repo: Path, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    items = ranking_items(payload)
    selected = payload.get("selected_idea_id") or payload.get("selected") or payload.get("selected_id")
    if not isinstance(selected, str) or not selected:
        raise IdeationStateError("ranking payload requires selected_idea_id")

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        ideas = phase_state.setdefault("idea_states", {})
        terminal_ids = {idea["id"] for idea in terminal_ideas(state)}
        ranked_ids = {item["idea_id"] for item in items}
        missing = sorted(terminal_ids - ranked_ids)
        if missing:
            raise IdeationStateError(f"ranking missing terminal ideas: {', '.join(missing)}")
        plain_rank = 1
        for item in items:
            idea = ideas.get(item["idea_id"])
            if not isinstance(idea, dict):
                raise IdeationStateError(f"ranking references unknown idea: {item['idea_id']}")
            idea["score"] = item["score"]
            idea["score_components"] = item.get("score_components") or item.get("components")
            idea["rationale"] = item.get("rationale")
            idea["risk_flags"] = item.get("risk_flags")
            if idea.get("evaluation") == "ACCEPTED":
                idea["rank"] = int(item.get("rank") or plain_rank)
                plain_rank += 1
            else:
                idea["rank"] = None
            idea["researchable"] = is_researchable_idea(idea, cfg)
            idea["selected"] = idea["id"] == selected
        candidates = researchable_candidates(state, cfg)
        candidate_ids = {idea["id"] for idea in candidates}
        if selected not in candidate_ids:
            raise IdeationStateError("selected_idea_id must be researchable under frozen mode config")
        phase_state["ranking"] = {
            "status": "final",
            "selected_idea_id": selected,
            "ranked_at": utc_now(),
            "rationale": payload.get("rationale"),
            "ranking_ref": str(write_payload_log(target_repo, run_id, "ranking", "ranking-final.json", payload)),
        }
        phase_state["handoff"] = {
            "status": "ready",
            "selected_idea_id": selected,
            "candidates": [
                {
                    "idea_id": idea["id"],
                    "evaluation": idea.get("evaluation"),
                    "score": idea.get("score"),
                    "rank": idea.get("rank"),
                    "idea_hash": idea.get("idea_hash"),
                }
                for idea in candidates
            ],
            "config_snapshot": {"strictness_mode": cfg.get("strictness_mode"), "mode_preset": mode_preset(cfg)},
        }
        clear_pending_intent_for_role(phase_state, "ranker")
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "selection", {"command": "ideation rank-finalize", "selected_idea_id": selected}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def completion_audit(state: dict[str, Any], config: dict[str, Any], status: str) -> dict[str, Any]:
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    candidates = researchable_candidates(state, config)
    return {
        "passed": True,
        "status": status,
        "prompt_to_artifact_checklist": [
            f"Attempted {phase_state.get('attempted_slots')} ideation slots",
            f"Recorded {len(terminal_ideas(state))} terminal idea records",
            f"Identified {len(candidates)} researchable candidates",
        ],
        "verification_evidence": [
            f".ai-scientist/runs/{state.get('run_id')}/loop-state.json",
            f".ai-scientist/runs/{state.get('run_id')}/ideas.json",
            f".ai-scientist/runs/{state.get('run_id')}/journal.jsonl",
        ],
    }


def final_summary(state: dict[str, Any]) -> dict[str, Any]:
    attempted = []
    for idea in terminal_ideas(state):
        attempted.append(
            {
                "idea_id": idea.get("id"),
                "evaluation": idea.get("evaluation"),
                "score": idea.get("score"),
                "reason": idea.get("rejection_reason") or idea.get("exhaustion_reason"),
                "critic_verdict": (idea.get("latest_critic") or {}).get("verdict") if isinstance(idea.get("latest_critic"), dict) else None,
            }
        )
    return {"attempted_ideas": attempted, "reason": "no researchable candidate was produced"}


def complete_ideation(target_repo: Path, run_id: str, *, budget_exhausted: bool = False) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        if isinstance(phase_state.get("pending_intent"), dict):
            raise IdeationStateError("pending subagent intent blocks completion")
        if phase_state.get("active_idea_id"):
            raise IdeationStateError("active idea blocks completion")
        required = int(phase_state.get("num_ideas_required") or 0)
        attempted = int(phase_state.get("attempted_slots") or 0)
        if attempted < required and not phase_state.get("early_stop_allowed") and not budget_exhausted:
            raise IdeationStateError("not all requested idea slots have been attempted")
        candidates = researchable_candidates(state, cfg)
        if len(candidates) < int(phase_state.get("min_candidates_required") or 1):
            raise IdeationStateError("not enough researchable candidates")
        ranking = phase_state.get("ranking") if isinstance(phase_state.get("ranking"), dict) else {}
        if ranking.get("status") != "final":
            raise IdeationStateError("ranking must be finalized before completion")
        selected = ranking.get("selected_idea_id")
        if not isinstance(selected, str) or selected not in {idea["id"] for idea in candidates}:
            raise IdeationStateError("selected idea must be researchable")
        status = "COMPLETED_BUDGET_EXHAUSTED" if budget_exhausted else "COMPLETED"
        state["active"] = False
        state["phase_status"] = status
        state["run_outcome"] = status
        state["completed_at"] = utc_now()
        state["completion_audit"] = completion_audit(state, cfg, status)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation complete", "budget_exhausted": budget_exhausted}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    append_journal_event(target_repo, run_id, "validation", details={"gate": "ideation_to_research", "exit_code": 0, "validator_exit_code": 0, "command": "ideation complete"})
    append_journal_event(target_repo, run_id, "handoff", details={"gate": "ideation_to_research", "approved": True, "exit_code": 0, "validator_exit_code": 0, "reason": "ideation handoff ready"})
    set_active_run(target_repo, run_id, "ideation", "completed")
    return updated


def exhaust_ideation(target_repo: Path, run_id: str) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    state = ensure_active_ideation_state(target_repo, run_id)
    if researchable_candidates(state, cfg):
        return complete_ideation(target_repo, run_id, budget_exhausted=True)

    def mutator(new_state: dict[str, Any]) -> None:
        phase_state = new_state.setdefault("state", {})
        if isinstance(phase_state.get("pending_intent"), dict):
            raise IdeationStateError("pending subagent intent blocks exhaustion")
        if phase_state.get("active_idea_id"):
            raise IdeationStateError("active idea blocks exhaustion; reject or exhaust the idea first")
        new_state["active"] = False
        new_state["phase_status"] = "EXHAUSTED_NO_CANDIDATE"
        new_state["run_outcome"] = "EXHAUSTED_NO_CANDIDATE"
        new_state["completed_at"] = utc_now()
        phase_state["final_summary"] = final_summary(new_state)
        new_state["completion_audit"] = completion_audit(new_state, cfg, "EXHAUSTED_NO_CANDIDATE")
        update_cursor(new_state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation exhaust"}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    append_journal_event(target_repo, run_id, "handoff", details={"gate": "ideation_to_research", "approved": False, "exit_code": 1, "validator_exit_code": 1, "reason": "no researchable candidate"})
    set_active_run(target_repo, run_id, "ideation", "exhausted")
    return updated


def cancel_ideation(target_repo: Path, run_id: str, reason: str) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        pending = phase_state.get("pending_intent")
        if isinstance(pending, dict):
            pending["status"] = "cancelled"
            pending["reason"] = reason
            pending["completed_at"] = utc_now()
            intent_id = pending.get("intent_id")
            if isinstance(intent_id, str):
                phase_state.setdefault("intents", {}).setdefault(intent_id, {}).update(pending)
            phase_state["pending_intent"] = None
        state["active"] = False
        state["phase_status"] = "CANCELLED"
        state["run_outcome"] = "CANCELLED"
        state["cancellation_reason"] = reason
        state["completed_at"] = utc_now()
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation cancel", "reason": reason}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    set_active_run(target_repo, run_id, "ideation", "cancelled")
    return updated

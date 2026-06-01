#!/usr/bin/env python3
"""Hook entrypoint for the AI Scientist ideation control plane."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ai_scientist_codex.ideation.finalize import finalize_ideation
from ai_scientist_codex.ideation.state import (
    advance_after_search,
    add_finalized_idea,
    extract_prompt,
    initialize_ideation,
    is_ideation_command,
    load_active_state,
    mark_blocked,
    next_instruction,
    parse_action_text,
    record_action,
    register_stop_continuation,
    register_stop_block,
    save_draft,
    save_state,
    skip_current_idea,
    snapshot_reflection,
    run_dir,
)
from ai_scientist_codex.ideation.evidence import search_and_record
from ai_scientist_codex.ideation.validate import validate_idea


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def payload_prompt(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def payload_target_repo(payload: dict[str, Any]) -> Path:
    value = payload.get("cwd") or payload.get("target_repo") or os.environ.get("PWD") or "."
    return Path(str(value)).resolve()


def payload_last_message(payload: dict[str, Any]) -> str:
    for key in ("last_agent_message", "last_message", "response", "assistant_message", "output"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def emit_context(message: str, **fields: Any) -> int:
    print(json.dumps({"message": message, **fields}, indent=2, sort_keys=True))
    return 0


def handle_session_start(payload: dict[str, Any]) -> int:
    target_repo = payload_target_repo(payload)
    state = load_active_state(target_repo)
    if not state:
        return 0
    return emit_context(next_instruction(state), event="SessionStart", run_id=state["run_id"])


def handle_user_prompt_submit(payload: dict[str, Any]) -> int:
    target_repo = payload_target_repo(payload)
    prompt = payload_prompt(payload)
    if not is_ideation_command(prompt):
        state = load_active_state(target_repo)
        if state and state.get("status") == "active":
            return emit_context(next_instruction(state), event="UserPromptSubmit", run_id=state["run_id"], active=True)
        return 0
    research_prompt = extract_prompt(prompt)
    state = initialize_ideation(
        target_repo,
        research_prompt,
        codex_thread_id=payload.get("thread_id"),
        turn_id=payload.get("turn_id"),
    )
    return emit_context(next_instruction(state), event="UserPromptSubmit", run_id=state["run_id"], active=True)


def action_name(parsed: dict[str, Any]) -> str:
    return str(parsed.get("action", "")).strip().lower()


def handle_search(target_repo: Path, state: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    arguments = parsed.get("arguments") or {}
    query = str(arguments.get("query", "")).strip()
    if not query:
        return register_stop_block(target_repo, state, "search_action_missing_query")
    _, cache_path = search_and_record(
        target_repo,
        state["run_id"],
        query,
        state["current_idea_id"],
        int(state.get("reflection_round", 0)) + 1,
    )
    return advance_after_search(target_repo, state, cache_path)


def handle_finalize(target_repo: Path, state: dict[str, Any], parsed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    arguments = parsed.get("arguments") or {}
    idea = arguments.get("idea")
    if not isinstance(idea, dict):
        return register_stop_block(target_repo, state, "finalize_action_missing_idea"), None
    state, _ = save_draft(target_repo, state, idea)
    search_root = run_dir(target_repo, state["run_id"]) / "semantic-scholar-cache"
    search_files = sorted(search_root.glob("*.json")) if search_root.exists() else []
    errors = validate_idea(idea, search_files)
    if errors:
        state["next_action"] = {"type": "reflect_or_finalize", "validator_errors": errors}
        state = register_stop_block(target_repo, state, "idea_validation_failed:" + "|".join(errors))
        return state, {"validation_errors": errors}
    return add_finalized_idea(target_repo, state, idea), None


def handle_stop(payload: dict[str, Any]) -> int:
    target_repo = payload_target_repo(payload)
    state = load_active_state(target_repo)
    if not state or state.get("status") == "blocked":
        return 0 if not state else emit_context(next_instruction(state), event="Stop", run_id=state["run_id"])
    if state.get("status") == "ready_to_finalize":
        result = finalize_ideation(target_repo, state)
        return emit_context("AI Scientist ideation finalized." if result.get("ok") else "AI Scientist ideation needs attention.", event="Stop", run_id=state["run_id"], result=result)
    state = register_stop_continuation(target_repo, state)
    if state.get("status") == "blocked":
        return emit_context(next_instruction(state), event="Stop", run_id=state["run_id"])

    last_message = payload_last_message(payload)
    if not last_message:
        state = register_stop_block(target_repo, state, "missing_last_agent_message")
        return emit_context(next_instruction(state), event="Stop", run_id=state["run_id"])

    state, action_file = record_action(target_repo, state, last_message, payload)
    try:
        parsed = parse_action_text(last_message)
    except ValueError as exc:
        state = register_stop_block(target_repo, state, f"missing_parseable_action:{exc}")
        return emit_context(next_instruction(state), event="Stop", run_id=state["run_id"], action_file=str(action_file))
    if int(state.get("reflection_round", 0)) > 0:
        snapshot_reflection(target_repo, state, last_message)

    name = action_name(parsed)
    extra: dict[str, Any] = {}
    if name == "searchsemanticscholar":
        state = handle_search(target_repo, state, parsed)
    elif name == "finalizeidea":
        state, extra = handle_finalize(target_repo, state, parsed)
        extra = extra or {}
    elif name == "skipidea":
        state = skip_current_idea(target_repo, state, "agent_requested_skip")
    else:
        state = register_stop_block(target_repo, state, f"unknown_action:{parsed.get('action')}")

    if state.get("status") == "ready_to_finalize":
        result = finalize_ideation(target_repo, state)
        return emit_context("AI Scientist ideation finalized." if result.get("ok") else "AI Scientist ideation needs attention.", event="Stop", run_id=state["run_id"], result=result, **extra)
    return emit_context(next_instruction(state), event="Stop", run_id=state["run_id"], action_file=str(action_file), **extra)


def command_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    for key in ("command", "cmd", "input"):
        value = payload.get(key) or tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


def handle_pre_tool_use(payload: dict[str, Any]) -> int:
    target_repo = payload_target_repo(payload)
    state = load_active_state(target_repo)
    if not state or state.get("status") != "active":
        return 0
    text = command_text(payload)
    blocked_patterns = ["codex exec", "ideation_orchestrator.py --agent-runner codex"]
    if any(pattern in text for pattern in blocked_patterns):
        mark_blocked(target_repo, state, "blocked_tool_pattern")
        print(json.dumps({"decision": "block", "reason": "blocked_tool_pattern", "message": "Ideation runs in the live session; do not launch nested Codex execution."}, indent=2, sort_keys=True))
        return 2
    print(json.dumps({"decision": "allow", "message": "Ideation tool hook guard passed."}, indent=2, sort_keys=True))
    return 0


def handle_post_tool_use(payload: dict[str, Any]) -> int:
    target_repo = payload_target_repo(payload)
    state = load_active_state(target_repo)
    if not state or state.get("status") != "active":
        return 0
    state["last_tool_payload"] = {key: payload.get(key) for key in ("tool_name", "return_code", "status") if key in payload}
    save_state(target_repo, state)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=["SessionStart", "UserPromptSubmit", "Stop", "PreToolUse", "PostToolUse"])
    args = parser.parse_args(argv)
    payload = read_payload()
    handlers = {
        "SessionStart": handle_session_start,
        "UserPromptSubmit": handle_user_prompt_submit,
        "Stop": handle_stop,
        "PreToolUse": handle_pre_tool_use,
        "PostToolUse": handle_post_tool_use,
    }
    return handlers[args.event](payload)


if __name__ == "__main__":
    raise SystemExit(main())

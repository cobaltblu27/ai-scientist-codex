#!/usr/bin/env python3
"""Durable state helpers for hook-driven AI Scientist ideation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
EXPLICIT_IDEATION_PREFIXES = ("/ideate", "$ai-scientist ideate", "ai-scientist: ideate")
DEFAULT_TARGET_NUM_IDEAS = 10
DEFAULT_MAX_REFLECTIONS = 5
DEFAULT_MAX_STOP_CONTINUATIONS = 12
DEFAULT_MAX_REPEATED_BLOCK_COUNT = 3

IDEA_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "title",
        "hypothesis",
        "scientific_insight",
        "related_work",
        "abstract",
        "novelty_rationale",
        "required_data",
        "expected_metric",
        "execution_plan",
        "experiments",
        "risks",
        "minimum_evidence",
    ],
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string", "minLength": 12},
        "hypothesis": {"type": "string", "minLength": 80},
        "scientific_insight": {"type": "string", "minLength": 120},
        "related_work": {"type": "string", "minLength": 120},
        "abstract": {"type": "string", "minLength": 180},
        "novelty_rationale": {"type": "string", "minLength": 80},
        "required_data": {"type": "string", "minLength": 40},
        "expected_metric": {"type": "string", "minLength": 40},
        "execution_plan": {
            "type": "array",
            "minItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["step", "purpose", "dataset", "model", "evaluation", "method", "success_criteria"],
                "properties": {
                    "step": {"type": "string", "minLength": 8},
                    "purpose": {"type": "string", "minLength": 20},
                    "dataset": {"type": "string", "minLength": 8},
                    "model": {"type": "string", "minLength": 8},
                    "evaluation": {"type": "string", "minLength": 8},
                    "method": {"type": "string", "minLength": 40},
                    "success_criteria": {"type": "string", "minLength": 20},
                },
            },
        },
        "experiments": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 40}},
        "risks": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 20}},
        "minimum_evidence": {"type": "array", "minItems": 4, "items": {"type": "string", "minLength": 30}},
        "semantic_scholar_queries": {"type": "array", "items": {"type": "string"}},
        "source_run_id": {"type": "string"},
        "reflection_count": {"type": "integer", "minimum": 1},
    },
}

IDEATION_PROTOCOL = """AI Scientist ideation is active.

Use the AI-Scientist-v2-style action protocol. Return exactly one action each turn:

ACTION:
SearchSemanticScholar
ARGUMENTS:
{"query": "..."}

or:

ACTION:
FinalizeIdea
ARGUMENTS:
{"idea": { ... }}

Rules:
- Perform at least one Semantic Scholar search before finalizing each idea.
- Keep proposals simple, falsifiable, and feasible for an academic lab.
- Final ideas must include hypothesis, scientific_insight, related_work, abstract,
  novelty_rationale, required_data, expected_metric, execution_plan, experiments,
  risks, and minimum_evidence.
- The execution_plan must explicitly name dataset, model, and evaluation details.
- If search results or validation feedback expose weakness, refine the idea before finalizing.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "ideation")[:max_len].strip("-") or "ideation"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def ai_dir(target_repo: Path) -> Path:
    return target_repo.resolve() / ".ai-scientist"


def run_dir(target_repo: Path, run_id: str) -> Path:
    return ai_dir(target_repo) / "runs" / run_id


def relative_to_run(path: Path, run_root: Path) -> str:
    return str(path.relative_to(run_root))


def is_ideation_command(prompt: str) -> bool:
    stripped = prompt.lstrip()
    return any(stripped.startswith(prefix) for prefix in EXPLICIT_IDEATION_PREFIXES)


def extract_prompt(prompt: str) -> str:
    stripped = prompt.strip()
    for prefix in EXPLICIT_IDEATION_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip() or "Generate AI Scientist research ideas for this repository."
    return stripped


def first_idea_id(index: int = 1) -> str:
    return f"idea-{index:03d}"


def snapshot_repo(target_repo: Path) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    ignored_dirs = {".git", ".ai-scientist", "__pycache__"}
    for path in sorted(target_repo.resolve().rglob("*")):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.relative_to(target_repo).parts):
            continue
        data = path.read_bytes()
        snapshot[str(path.relative_to(target_repo))] = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return snapshot


def diff_snapshot(target_repo: Path, baseline: dict[str, dict[str, Any]]) -> list[str]:
    current = snapshot_repo(target_repo)
    changes = sorted(set(current) ^ set(baseline))
    for path, meta in current.items():
        if path in baseline and baseline[path].get("sha256") != meta.get("sha256"):
            changes.append(path)
    return sorted(set(changes))


def active_pointer_path(target_repo: Path) -> Path:
    return ai_dir(target_repo) / "state" / "active-ideation.json"


def load_active_state(target_repo: Path) -> dict[str, Any] | None:
    pointer_path = active_pointer_path(target_repo)
    if not pointer_path.exists():
        return None
    pointer = read_json(pointer_path)
    state_file = target_repo.resolve() / pointer["state_file"]
    if not state_file.exists():
        return None
    state = read_json(state_file)
    if state.get("status") in {"active", "blocked", "ready_to_finalize"}:
        return state
    return None


def save_state(target_repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = utc_now()
    state_path = run_dir(target_repo, state["run_id"]) / "ideation-state.json"
    write_json(state_path, state)
    write_json(
        active_pointer_path(target_repo),
        {
            "run_id": state["run_id"],
            "status": state["status"],
            "state_file": str(state_path.relative_to(target_repo.resolve())),
            "updated_at": state["updated_at"],
        },
    )
    return state


def initialize_ideation(
    target_repo: Path,
    prompt: str,
    *,
    run_id: str | None = None,
    strictness_mode: str = "scientist",
    benchmark: str = "unspecified",
    split_policy: str = "Preserve the declared benchmark split; clarify before research if unspecified.",
    target_num_ideas: int = DEFAULT_TARGET_NUM_IDEAS,
    max_reflections: int = DEFAULT_MAX_REFLECTIONS,
    max_stop_continuations: int = DEFAULT_MAX_STOP_CONTINUATIONS,
    max_repeated_block_count: int = DEFAULT_MAX_REPEATED_BLOCK_COUNT,
    codex_thread_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, Any]:
    target_repo = target_repo.resolve()
    if strictness_mode not in MODES:
        raise ValueError(f"strictness_mode must be one of {sorted(MODES)}")
    if target_num_ideas <= 0:
        raise ValueError("target_num_ideas must be positive")
    if max_reflections <= 0:
        raise ValueError("max_reflections must be positive")
    run_id = run_id or f"ideation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{slugify(prompt)}"
    root = ai_dir(target_repo)
    current_run = run_dir(target_repo, run_id)
    logs = root / "logs" / run_id
    for path in [
        root / "ideas",
        root / "state",
        current_run / "actions",
        current_run / "drafts",
        current_run / "reflections",
        current_run / "semantic-scholar-cache",
        logs / "semantic-scholar-cache",
    ]:
        path.mkdir(parents=True, exist_ok=True)

    write_json(
        root / "config.json",
        {
            "schema_version": "ai-scientist-config-v1",
            "strictness_mode": strictness_mode,
            "target_repo": str(target_repo),
            "benchmark": benchmark,
            "split_policy": split_policy,
            "api_budgets": {
                "semantic_scholar": {
                    "phase": "ideation",
                    "max_queries": target_num_ideas * max_reflections,
                    "max_results_per_query": 10,
                }
            },
            "s2_enabled": True,
            "ideation": {
                "run_id": run_id,
                "loop_driver": "hooks",
                "target_num_ideas": target_num_ideas,
                "max_reflections": max_reflections,
            },
        },
    )
    write_json(current_run / "dependency-plan.json", {"planned_dependencies": []})
    write_json(current_run / "filesystem-baseline.json", snapshot_repo(target_repo))
    (current_run / "api-ledger.jsonl").touch()
    write_json(
        current_run / "journal.json",
        {
            "run_id": run_id,
            "phase": "ideation",
            "created_at": utc_now(),
            "entries": [{"timestamp": utc_now(), "event": "ideation_started", "prompt": prompt}],
        },
    )
    write_json(
        current_run / "principles.json",
        {
            "principles": [
                {
                    "name": "Auditable hook-driven ideation",
                    "gates": ["ideation_to_research"],
                    "evidence_artifacts": [
                        ".ai-scientist/runs/<run-id>/ideation-state.json",
                        ".ai-scientist/runs/<run-id>/actions/",
                        ".ai-scientist/runs/<run-id>/drafts/",
                    ],
                }
            ]
        },
    )

    state = {
        "schema_version": "ai-scientist-ideation-state-v1",
        "run_id": run_id,
        "target_repo": str(target_repo),
        "phase": "ideation",
        "status": "active",
        "reason": None,
        "prompt": prompt,
        "strictness_mode": strictness_mode,
        "benchmark": benchmark,
        "split_policy": split_policy,
        "target_num_ideas": target_num_ideas,
        "max_reflections": max_reflections,
        "current_idea_id": first_idea_id(),
        "current_idea_index": 1,
        "reflection_round": 0,
        "literature_search_done": False,
        "finalized_ideas": [],
        "skipped_ideas": [],
        "codex_thread_id": codex_thread_id,
        "turn_id": turn_id,
        "stop_continuations": 0,
        "max_stop_continuations": max_stop_continuations,
        "last_block_reason_hash": None,
        "repeated_block_count": 0,
        "max_repeated_block_count": max_repeated_block_count,
        "next_user_action_required": False,
        "action_count": 0,
        "search_count": 0,
        "last_action_file": None,
        "last_search_file": None,
        "current_draft_file": None,
        "next_action": {"type": "propose", "idea_id": first_idea_id()},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    save_state(target_repo, state)
    write_json(logs / "ideation-run.json", {"run_id": run_id, "prompt": prompt, "ideas": [], "started_at": state["created_at"]})
    return state


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in fenced:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("text did not contain a JSON object")


def parse_action_text(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        candidate = extract_json_object(text)
        action = candidate.get("action") or candidate.get("ACTION")
        if action:
            return {"action": str(action), "arguments": candidate.get("arguments") or candidate.get("ARGUMENTS") or candidate}
    except Exception:
        pass

    action_match = re.search(r"ACTION:\s*([A-Za-z_][A-Za-z0-9_]*)\s*ARGUMENTS:", text, re.DOTALL | re.IGNORECASE)
    if not action_match:
        raise ValueError("missing ACTION/ARGUMENTS block")
    action = action_match.group(1).strip()
    args_text = text[action_match.end() :].strip()
    if args_text.startswith("```json"):
        block = re.search(r"```json\s*(.*?)\s*```", args_text, re.DOTALL)
        if block:
            args_text = block.group(1).strip()
    arguments = extract_json_object(args_text)
    return {"action": action, "arguments": arguments}


def record_action(target_repo: Path, state: dict[str, Any], text: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], Path]:
    state["action_count"] = int(state.get("action_count", 0)) + 1
    turn_id = (payload or {}).get("turn_id") or state.get("turn_id") or f"turn-{state['action_count']:04d}"
    path = run_dir(target_repo, state["run_id"]) / "actions" / f"{turn_id}-{state['action_count']:04d}.json"
    record = {
        "timestamp": utc_now(),
        "turn_id": turn_id,
        "idea_id": state.get("current_idea_id"),
        "reflection_round": state.get("reflection_round"),
        "raw_text": text,
        "payload": payload or {},
    }
    try:
        record["parsed_action"] = parse_action_text(text)
    except ValueError as exc:
        record["parse_error"] = str(exc)
    write_json(path, record)
    state["last_action_file"] = relative_to_run(path, run_dir(target_repo, state["run_id"]))
    return save_state(target_repo, state), path


def snapshot_reflection(target_repo: Path, state: dict[str, Any], text: str) -> Path:
    idea_id = state["current_idea_id"]
    round_index = max(1, int(state.get("reflection_round", 0)))
    path = run_dir(target_repo, state["run_id"]) / "reflections" / f"{idea_id}-r{round_index}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n")
    return path


def save_draft(target_repo: Path, state: dict[str, Any], idea: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    idea_id = str(idea.get("id") or state["current_idea_id"])
    idea["id"] = idea_id
    round_index = max(1, int(state.get("reflection_round", 0)))
    path = run_dir(target_repo, state["run_id"]) / "drafts" / f"{idea_id}_r{round_index}.json"
    write_json(path, idea)
    state["current_draft_file"] = relative_to_run(path, run_dir(target_repo, state["run_id"]))
    return save_state(target_repo, state), path


def append_journal(target_repo: Path, run_id: str, event: str, **fields: Any) -> None:
    path = run_dir(target_repo, run_id) / "journal.json"
    journal = read_json(path)
    journal.setdefault("entries", []).append({"timestamp": utc_now(), "event": event, **fields})
    write_json(path, journal)


def advance_after_search(target_repo: Path, state: dict[str, Any], search_file: Path) -> dict[str, Any]:
    state["reflection_round"] = int(state.get("reflection_round", 0)) + 1
    state["literature_search_done"] = True
    state["search_count"] = int(state.get("search_count", 0)) + 1
    state["last_search_file"] = relative_to_run(search_file, run_dir(target_repo, state["run_id"]))
    state["next_action"] = {
        "type": "reflect_or_finalize",
        "idea_id": state["current_idea_id"],
        "reflection_round": state["reflection_round"],
        "search_file": state["last_search_file"],
    }
    append_journal(target_repo, state["run_id"], "semantic_scholar_search_completed", idea_id=state["current_idea_id"], search_file=state["last_search_file"])
    return save_state(target_repo, state)


def add_finalized_idea(target_repo: Path, state: dict[str, Any], idea: dict[str, Any]) -> dict[str, Any]:
    idea = dict(idea)
    idea["id"] = state["current_idea_id"]
    idea["source_run_id"] = state["run_id"]
    idea["reflection_count"] = max(1, int(state.get("reflection_round", 0)))
    state["finalized_ideas"].append(idea)
    append_journal(target_repo, state["run_id"], "idea_finalized", idea_id=idea["id"], reflection_count=idea["reflection_count"])
    ideas_path = ai_dir(target_repo) / "ideas" / "ideas.json"
    write_json(ideas_path, {"ideas": state["finalized_ideas"]})
    return advance_to_next_idea_or_finalize(target_repo, state)


def skip_current_idea(target_repo: Path, state: dict[str, Any], reason: str) -> dict[str, Any]:
    state["skipped_ideas"].append({"id": state["current_idea_id"], "reason": reason, "reflection_round": state.get("reflection_round", 0)})
    append_journal(target_repo, state["run_id"], "idea_skipped", idea_id=state["current_idea_id"], reason=reason)
    return advance_to_next_idea_or_finalize(target_repo, state)


def advance_to_next_idea_or_finalize(target_repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    if len(state["finalized_ideas"]) >= int(state["target_num_ideas"]):
        state["status"] = "ready_to_finalize"
        state["next_action"] = {"type": "finalize_run"}
        return save_state(target_repo, state)
    if int(state["current_idea_index"]) >= int(state["target_num_ideas"]):
        state["status"] = "ready_to_finalize" if state["finalized_ideas"] else "failed"
        state["reason"] = None if state["finalized_ideas"] else "no_finalized_ideas"
        state["next_action"] = {"type": "finalize_run" if state["finalized_ideas"] else "report_failure"}
        return save_state(target_repo, state)
    next_index = int(state["current_idea_index"]) + 1
    state["current_idea_index"] = next_index
    state["current_idea_id"] = first_idea_id(next_index)
    state["reflection_round"] = 0
    state["literature_search_done"] = False
    state["stop_continuations"] = 0
    state["last_block_reason_hash"] = None
    state["repeated_block_count"] = 0
    state["last_search_file"] = None
    state["current_draft_file"] = None
    state["next_action"] = {"type": "propose", "idea_id": state["current_idea_id"]}
    return save_state(target_repo, state)


def mark_blocked(target_repo: Path, state: dict[str, Any], reason: str) -> dict[str, Any]:
    state["status"] = "blocked"
    state["reason"] = reason
    state["next_user_action_required"] = True
    state["next_action"] = {"type": "await_user", "reason": reason}
    append_journal(target_repo, state["run_id"], "ideation_blocked", reason=reason)
    return save_state(target_repo, state)


def register_stop_block(target_repo: Path, state: dict[str, Any], reason: str) -> dict[str, Any]:
    digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()
    if state.get("last_block_reason_hash") == digest:
        state["repeated_block_count"] = int(state.get("repeated_block_count", 0)) + 1
    else:
        state["last_block_reason_hash"] = digest
        state["repeated_block_count"] = 1
    if int(state["repeated_block_count"]) > int(state["max_repeated_block_count"]):
        return mark_blocked(target_repo, state, "repeated_stop_hook_block")
    return save_state(target_repo, state)


def register_stop_continuation(target_repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    state["stop_continuations"] = int(state.get("stop_continuations", 0)) + 1
    if int(state["stop_continuations"]) > int(state["max_stop_continuations"]):
        return mark_blocked(target_repo, state, "max_stop_continuations_exceeded")
    return save_state(target_repo, state)


def next_instruction(state: dict[str, Any]) -> str:
    if state.get("status") == "blocked":
        return f"AI Scientist ideation is blocked: {state.get('reason')}. Ask the user before continuing."
    action = state.get("next_action") or {}
    header = f"Run `{state['run_id']}` idea `{state.get('current_idea_id')}` round `{state.get('reflection_round')}`."
    if action.get("type") == "propose":
        task = "Generate one distinct proposal, then choose SearchSemanticScholar with a concrete query."
    elif action.get("type") == "reflect_or_finalize":
        task = "Read the latest search/cache results, reflect on novelty and feasibility, then either search again or finalize."
    elif action.get("type") == "finalize_run":
        task = "Finalize the ideation run artifacts."
    else:
        task = "Continue from the active ideation state."
    return f"{IDEATION_PROTOCOL}\n{header}\nNext task: {task}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--target-repo", type=Path, default=Path.cwd())
    start.add_argument("--prompt", required=True)
    start.add_argument("--run-id")
    start.add_argument("--strictness-mode", choices=sorted(MODES), default="scientist")
    start.add_argument("--benchmark", default="unspecified")
    start.add_argument("--split-policy", default="Preserve the declared benchmark split; clarify before research if unspecified.")
    start.add_argument("--num-ideas", type=int, default=DEFAULT_TARGET_NUM_IDEAS)
    start.add_argument("--num-reflections", type=int, default=DEFAULT_MAX_REFLECTIONS)

    args = parser.parse_args()
    if args.command == "start":
        state = initialize_ideation(
            args.target_repo,
            args.prompt,
            run_id=args.run_id,
            strictness_mode=args.strictness_mode,
            benchmark=args.benchmark,
            split_policy=args.split_policy,
            target_num_ideas=args.num_ideas,
            max_reflections=args.num_reflections,
        )
        print(json.dumps({"state": state, "instruction": next_instruction(state)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

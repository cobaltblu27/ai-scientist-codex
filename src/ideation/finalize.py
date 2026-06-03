#!/usr/bin/env python3
"""Finalize hook-driven ideation artifacts and run the ideation gate."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.plugin import plugin_root as default_plugin_root
from ideation.state import ai_dir, append_journal, diff_snapshot, read_json, run_dir, save_state, utc_now, write_json
from ideation.validate import validate_idea


def write_gate_artifacts(target_repo: Path, run_id: str, strictness_mode: str, validator_exit_code: int) -> None:
    current_run = run_dir(target_repo, run_id)
    now = utc_now()
    validation = {
        "gate": "ideation_to_research",
        "exit_code": validator_exit_code,
        "validator_exit_code": validator_exit_code,
        "validated_at": now,
    }
    write_json(
        current_run / "run-status.json",
        {
            "run_id": run_id,
            "phase": "ideation",
            "status": "validated" if validator_exit_code == 0 else "validation_failed",
            "strictness_mode": strictness_mode,
            "last_validation": validation,
            "last_validations": {"ideation_to_research": validation},
        },
    )
    handoff = {
        "run_id": run_id,
        "from_phase": "ideation",
        "to_phase": "research",
        "gate": "ideation_to_research",
        "owner": "hook-driven-ideation",
        "reviewer": "codex-live-session",
        "verifier": "ai-scientist validate run",
        "evidence_path": ".ai-scientist/ideas/ideas.json",
        "validator_exit_code": validator_exit_code,
        "approved": validator_exit_code == 0,
        "approved_at": now if validator_exit_code == 0 else None,
    }
    (current_run / "handoff.jsonl").write_text(json.dumps(handoff, sort_keys=True) + "\n")


def cache_files_for_state(target_repo: Path, state: dict[str, Any]) -> list[Path]:
    files: list[Path] = []
    current_run = run_dir(target_repo, state["run_id"])
    if state.get("last_search_file"):
        candidate = current_run / state["last_search_file"]
        if candidate.exists():
            files.append(candidate)
    cache_dir = ai_dir(target_repo) / "logs" / state["run_id"] / "semantic-scholar-cache"
    if cache_dir.exists():
        files.extend(sorted(path for path in cache_dir.glob("*.json") if path not in files))
    return files


def run_validator(plugin_root: Path, target_repo: Path, run_id: str) -> int:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "validation.run",
            str(target_repo),
            "--gate",
            "ideation_to_research",
            "--run-id",
            run_id,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    (run_dir(target_repo, run_id) / "ideation-validation-output.json").write_text(
        json.dumps({"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}, indent=2, sort_keys=True) + "\n"
    )
    return proc.returncode


def finalize_ideation(target_repo: Path, state: dict[str, Any], plugin_root: Path | None = None) -> dict[str, Any]:
    target_repo = target_repo.resolve()
    current_run = run_dir(target_repo, state["run_id"])
    baseline = read_json(current_run / "filesystem-baseline.json")
    changed_paths = diff_snapshot(target_repo, baseline)
    write_json(current_run / "ideation-runtime-mutation-check.json", {"passed": not changed_paths, "changed_paths": changed_paths})
    if changed_paths:
        state["status"] = "blocked"
        state["reason"] = "unexpected_repo_mutation"
        state["next_user_action_required"] = True
        save_state(target_repo, state)
        append_journal(target_repo, state["run_id"], "ideation_blocked", reason="unexpected_repo_mutation", changed_paths=changed_paths)
        return {"ok": False, "reason": "unexpected_repo_mutation", "changed_paths": changed_paths}

    ideas = list(state.get("finalized_ideas") or [])
    if not ideas:
        state["status"] = "failed"
        state["reason"] = "no_finalized_ideas"
        save_state(target_repo, state)
        write_gate_artifacts(target_repo, state["run_id"], state["strictness_mode"], 1)
        append_journal(target_repo, state["run_id"], "ideation_failed", reason="no_finalized_ideas")
        return {"ok": False, "reason": "no_finalized_ideas"}

    validation_errors: dict[str, list[str]] = {}
    search_files = cache_files_for_state(target_repo, state)
    for idea in ideas:
        errors = validate_idea(idea, search_files)
        if errors:
            validation_errors[str(idea.get("id", "unknown"))] = errors
    write_json(current_run / "idea-validation.json", {"passed": not validation_errors, "errors": validation_errors})
    if validation_errors:
        state["status"] = "blocked"
        state["reason"] = "idea_validation_failed"
        state["next_user_action_required"] = True
        save_state(target_repo, state)
        append_journal(target_repo, state["run_id"], "ideation_blocked", reason="idea_validation_failed")
        return {"ok": False, "reason": "idea_validation_failed", "errors": validation_errors}

    write_json(ai_dir(target_repo) / "ideas" / "ideas.json", {"ideas": ideas})
    write_json(ai_dir(target_repo) / "logs" / state["run_id"] / "final-ideas.json", {"ideas": ideas})
    write_json(ai_dir(target_repo) / "logs" / state["run_id"] / "skipped-ideas.json", {"skipped": state.get("skipped_ideas", [])})
    run_log_path = ai_dir(target_repo) / "logs" / state["run_id"] / "ideation-run.json"
    run_log = read_json(run_log_path)
    run_log.update(
        {
            "completed_at": utc_now(),
            "finalized_count": len(ideas),
            "skipped_count": len(state.get("skipped_ideas", [])),
            "ideas": [{"id": idea["id"], "status": "finalized", "reflection_count": idea.get("reflection_count")} for idea in ideas],
        }
    )
    write_json(run_log_path, run_log)

    write_gate_artifacts(target_repo, state["run_id"], state["strictness_mode"], 0)
    plugin_root = plugin_root or default_plugin_root(Path(__file__))
    validator_exit = run_validator(plugin_root, target_repo, state["run_id"])
    write_gate_artifacts(target_repo, state["run_id"], state["strictness_mode"], validator_exit)
    append_journal(target_repo, state["run_id"], "ideation_validation_completed", validator_exit_code=validator_exit)
    state["status"] = "finalized" if validator_exit == 0 else "blocked"
    state["reason"] = None if validator_exit == 0 else "validator_failed"
    state["next_user_action_required"] = validator_exit != 0
    state["next_action"] = {"type": "complete" if validator_exit == 0 else "await_user", "validator_exit_code": validator_exit}
    save_state(target_repo, state)
    return {"ok": validator_exit == 0, "validator_exit_code": validator_exit, "ideas_path": str(ai_dir(target_repo) / "ideas" / "ideas.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    state = read_json(run_dir(args.target_repo, args.run_id) / "ideation-state.json")
    result = finalize_ideation(args.target_repo, state)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

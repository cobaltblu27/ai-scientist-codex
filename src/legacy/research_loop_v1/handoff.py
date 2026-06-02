from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .journal import append_jsonl, utc_now, write_json


def artifact_snapshot(run_dir: Path) -> str:
    h = hashlib.sha256()
    ignored = {"handoff.jsonl", "run-status.json", "journal.json", "evidence-validation-output.json", "final-validation-output.json", "verifier-decision.json"}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name not in ignored and "verifier-decisions" not in path.parts:
            h.update(str(path.relative_to(run_dir)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def record_validation(run_dir: Path, gate: str, mode: str, exit_code: int, selected_node: str | None, metric_key: str, metric_direction: str, snapshot: str) -> dict[str, Any]:
    record = {"gate": gate, "validation_mode": mode, "exit_code": exit_code, "validated_at": utc_now(), "selected_node": selected_node, "metric_key": metric_key, "metric_direction": metric_direction, "artifact_snapshot": snapshot}
    status_path = run_dir / "run-status.json"
    status = json.loads(status_path.read_text())
    status["last_validation"] = record
    status.setdefault("last_validations", {})[gate] = record
    status["selected_node"] = selected_node
    status["artifact_snapshot"] = snapshot
    status["status"] = "validated" if exit_code == 0 else "blocked"
    write_json(status_path, status)
    return record


def append_approved_handoff(run_dir: Path, validation: dict[str, Any]) -> None:
    append_jsonl(
        run_dir / "handoff.jsonl",
        {
            "run_id": run_dir.name,
            "gate": "research_to_review",
            "from_phase": "research",
            "to_phase": "review",
            "owner": "ai-scientist research-loop run",
            "reviewer": "research-loop-finalizer",
            "verifier": "ai-scientist validate run",
            "evidence_path": ".ai-scientist/runs/<run-id>/selection.json",
            "approved": True,
            "validator_exit_code": 0,
            "approved_at": utc_now(),
            "validation": validation,
            "artifact_snapshot": validation["artifact_snapshot"],
        },
    )


def write_gate_decision(run_dir: Path, validation: dict[str, Any], evidence_command: list[str], final_command: list[str] | None = None) -> None:
    write_json(
        run_dir / "verifier-decisions" / "research_to_review.json",
        {
            "decision": "approved",
            "gate": "research_to_review",
            "reason": "evidence validation, handoff, governance, metric, prompt, and mutation checks passed",
            "validation": validation,
            "evidence_validation": validation,
            "evidence_validation_command": evidence_command,
            "final_validation_command": final_command,
            "artifact_snapshot": validation["artifact_snapshot"],
            "approved_at": utc_now(),
            "decided_at": utc_now(),
        },
    )


def run_validator(script_dir: Path, target_repo: Path, run_id: str, mode: str) -> tuple[int, str, list[str]]:
    cmd = [
        sys.executable,
        "-m",
        "validation.run",
        str(target_repo),
        "--gate",
        "research_to_review",
        "--run-id",
        run_id,
        "--validation-mode",
        mode,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return proc.returncode, proc.stdout + proc.stderr, cmd

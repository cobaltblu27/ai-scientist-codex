"""Scan a target repo's `.ai-scientist/` tree into plain JSON for the dashboard.

Read-only. Tolerates missing or malformed artifacts so a half-written run still
shows up in the UI with whatever is parseable.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.state import ai_root

JOURNAL_TAIL = 50


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Lenient JSONL read: skip lines that are not JSON objects."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def _epoch(iso: Any) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _node_summaries(run: Path) -> list[dict[str, Any]]:
    nodes_dir = run / "nodes"
    if not nodes_dir.is_dir():
        return []
    out = []
    for node_dir in sorted(p for p in nodes_dir.iterdir() if p.is_dir()):
        node = _load_json(node_dir / "node.json")
        if not isinstance(node, dict):
            node = {}
        out.append(
            {
                "node_id": node.get("node_id") or node_dir.name,
                "status": node.get("status"),
                "outcome_type": node.get("outcome_type"),
                "metrics": node.get("metrics") if isinstance(node.get("metrics"), dict) else {},
                "result_summary": node.get("result_summary"),
                "current_claim": node.get("current_claim"),
                "trial_count": len(node.get("trials") or []),
                "updated_at": _mtime(node_dir / "node.json"),
            }
        )
    return out


def run_summary(run: Path) -> dict[str, Any]:
    loop_state = _load_json(run / "loop-state.json")
    if not isinstance(loop_state, dict):
        loop_state = {}
    config = _load_json(run / "config.json")
    if not isinstance(config, dict):
        config = {}
    state = loop_state.get("state") if isinstance(loop_state.get("state"), dict) else {}
    orchestrator = state.get("orchestrator") if isinstance(state.get("orchestrator"), dict) else {}
    contract = config.get("research_contract") if isinstance(config.get("research_contract"), dict) else {}
    ideas = _load_json(run / "ideas.json")
    idea_count = len(ideas) if isinstance(ideas, list) else len(ideas) if isinstance(ideas, dict) else 0
    return {
        "run_id": loop_state.get("run_id") or run.name,
        "path": str(run),
        "active": bool(loop_state.get("active")),
        "phase": loop_state.get("phase"),
        "phase_status": loop_state.get("phase_status"),
        "run_outcome": loop_state.get("run_outcome"),
        "started_at": loop_state.get("started_at"),
        "updated_at": loop_state.get("updated_at"),
        "completed_at": loop_state.get("completed_at"),
        "completed_phases": sorted((loop_state.get("completed_phases") or {}).keys())
        if isinstance(loop_state.get("completed_phases"), dict)
        else [],
        "blocked_reason": loop_state.get("blocked_reason"),
        "next_action": orchestrator.get("next_action"),
        "iteration": orchestrator.get("iteration"),
        "current_node": orchestrator.get("current_node"),
        "selected_node": state.get("selected_node"),
        "goal": contract.get("goal") or contract.get("primary_hypothesis"),
        "primary_metric": (contract.get("metrics") or {}).get("primary") if isinstance(contract.get("metrics"), dict) else None,
        "idea_count": idea_count,
        "node_count": len(_node_summaries(run)),
        "mtime": _mtime(run / "loop-state.json") or _mtime(run),
    }


def run_detail(run: Path) -> dict[str, Any]:
    summary = run_summary(run)
    journal = _load_jsonl(run / "journal.jsonl")
    return {
        **summary,
        "nodes": _node_summaries(run),
        "journal": journal[-JOURNAL_TAIL:],
        "journal_count": len(journal),
        "selection": _load_json(run / "selection.json"),
        "loop_state": _load_json(run / "loop-state.json"),
        "config": _load_json(run / "config.json"),
    }


def _contracts(root: Path) -> list[dict[str, Any]]:
    contracts_dir = root / "contracts"
    if not contracts_dir.is_dir():
        return []
    out = []
    for d in sorted(p for p in contracts_dir.iterdir() if p.is_dir()):
        data = _load_json(d / "research-contract.json")
        contract = data.get("research_contract") if isinstance(data, dict) else None
        out.append(
            {
                "contract_id": d.name,
                "goal": (contract or {}).get("goal") if isinstance(contract, dict) else None,
                "valid": isinstance(contract, dict),
            }
        )
    return out


def scan_overview(target_repo: Path) -> dict[str, Any]:
    root = ai_root(target_repo)
    runs_dir = root / "runs"
    runs = []
    if runs_dir.is_dir():
        runs = [run_summary(p) for p in runs_dir.iterdir() if p.is_dir()]
    runs.sort(key=lambda r: _epoch(r.get("updated_at")) or r.get("mtime") or 0, reverse=True)
    active = _load_json(root / "active-run.json")
    return {
        "target_repo": str(target_repo),
        "ai_root": str(root),
        "exists": root.is_dir(),
        "active_run": active if isinstance(active, dict) else None,
        "runs": runs,
        "contracts": _contracts(root),
    }


def find_run(target_repo: Path, run_id: str) -> Path | None:
    if "/" in run_id or run_id in {".", ".."}:
        return None
    run = ai_root(target_repo) / "runs" / run_id
    return run if run.is_dir() else None

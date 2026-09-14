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


# Node statuses that mean an agent is still working the node (or may resume it).
# Everything else is terminal, and the graph draws it as dead.
LIVE_NODE_STATUSES = {
    "planned", "pending", "queued",
    "implementing", "running", "experimenting",
    "buggy", "repairing", "revising",
    "candidate", "validating",
}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _phase_state(run: Path) -> dict[str, Any]:
    loop_state = _load_json(run / "loop-state.json")
    if not isinstance(loop_state, dict):
        return {}
    state = loop_state.get("state")
    return state if isinstance(state, dict) else {}


def _official_nodes(phase_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`loop-state.state.nodes`: orchestrator-owned node ledger keyed by node id."""
    nodes = phase_state.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    return {str(k): v for k, v in nodes.items() if isinstance(v, dict)}


def _node_reports(run: Path, node_id: str) -> list[dict[str, Any]]:
    """Markdown reports written by agents for one node.

    Worker reports live at `logs/workers/<node-id>/<worker-id>/result.md` and
    revision reports at `logs/revisions/<node-id>/<revision-id>/result.md`.
    """
    out = []
    for kind, sub in (("worker", "workers"), ("revision", "revisions")):
        base = run / "logs" / sub / node_id
        if not base.is_dir():
            continue
        for agent_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            path = agent_dir / "result.md"
            if not path.is_file():
                continue
            out.append({"kind": kind, "agent_id": agent_dir.name, "path": str(path), "updated_at": _mtime(path)})
    out.sort(key=lambda r: r["updated_at"] or 0)
    return out


def _parent_of(node: dict[str, Any], official: dict[str, Any]) -> str | None:
    for source in (node, official):
        parent = source.get("parent_node_id")
        if isinstance(parent, str) and parent:
            return parent
    return None


def _depths(parents: dict[str, str | None]) -> dict[str, int]:
    """Depth = length of the parent chain. Unknown parents and cycles stop at the last resolvable node."""
    depths: dict[str, int] = {}

    def depth(node_id: str, seen: set[str]) -> int:
        if node_id in depths:
            return depths[node_id]
        parent = parents.get(node_id)
        if parent is None or parent not in parents or parent in seen:
            depths[node_id] = 0
        else:
            depths[node_id] = depth(parent, seen | {node_id}) + 1
        return depths[node_id]

    for node_id in parents:
        depth(node_id, set())
    return depths


def _node_summaries(run: Path) -> list[dict[str, Any]]:
    nodes_dir = run / "nodes"
    if not nodes_dir.is_dir():
        return []
    official_nodes = _official_nodes(_phase_state(run))
    raw: list[tuple[str, Path, dict[str, Any], dict[str, Any]]] = []
    for node_dir in sorted(p for p in nodes_dir.iterdir() if p.is_dir()):
        node = _load_json(node_dir / "node.json")
        if not isinstance(node, dict):
            node = {}
        node_id = str(node.get("node_id") or node_dir.name)
        raw.append((node_id, node_dir, node, official_nodes.get(node_id) or {}))

    parents = {node_id: _parent_of(node, official) for node_id, _, node, official in raw}
    depths = _depths(parents)
    out = []
    for node_id, node_dir, node, official in raw:
        status = node.get("status")
        official_status = official.get("status")
        effective = official_status or status
        out.append(
            {
                "node_id": node_id,
                "parent_node_id": parents[node_id],
                "depth": depths[node_id],
                "status": status,
                "official_status": official_status,
                "alive": str(effective) in LIVE_NODE_STATUSES,
                "outcome_type": node.get("outcome_type"),
                "metrics": node.get("metrics") if isinstance(node.get("metrics"), dict) else {},
                "result_summary": node.get("result_summary"),
                "current_claim": node.get("current_claim"),
                "trial_count": len(node.get("trials") or []),
                "report_count": len(_node_reports(run, node_id)),
                "updated_at": _mtime(node_dir / "node.json"),
            }
        )
    return out


def _node_history(run: Path, node_id: str, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological trail of what agents did to a node.

    Merges journal events tagged with the node, `loop-state.state.work` items that
    point at it, and the report files themselves. Newest last.
    """
    phase_state = _phase_state(run)
    work = phase_state.get("work") if isinstance(phase_state.get("work"), dict) else {}
    work_ids = {str(k) for k, v in work.items() if isinstance(v, dict) and v.get("node_id") == node_id}

    events: list[dict[str, Any]] = []
    for rec in _load_jsonl(run / "journal.jsonl"):
        agent = rec.get("subagent_id")
        if rec.get("node_id") != node_id and agent not in work_ids:
            continue
        details = rec.get("details") if isinstance(rec.get("details"), dict) else {}
        events.append(
            {
                "kind": "journal",
                "event_type": rec.get("event_type"),
                "agent_id": agent,
                "status": details.get("status"),
                "timestamp": rec.get("timestamp"),
                "epoch": _epoch(rec.get("timestamp")),
                "details": details,
            }
        )
    for work_id, item in work.items():
        if not isinstance(item, dict) or item.get("node_id") != node_id:
            continue
        events.append(
            {
                "kind": "work",
                "event_type": "work",
                "agent_id": str(work_id),
                "status": item.get("status"),
                "timestamp": item.get("updated_at"),
                "epoch": _epoch(item.get("updated_at")),
                "details": {k: v for k, v in item.items() if k not in {"node_id", "status", "updated_at"}},
            }
        )
    for report in reports:
        events.append(
            {
                "kind": "report",
                "event_type": f"{report['kind']}_report",
                "agent_id": report["agent_id"],
                "status": None,
                "timestamp": None,
                "epoch": report["updated_at"],
                "details": {"path": report["path"]},
            }
        )
    events.sort(key=lambda e: e.get("epoch") or 0)
    return events


def node_detail(run: Path, node_id: str) -> dict[str, Any] | None:
    summary = next((n for n in _node_summaries(run) if n["node_id"] == node_id), None)
    if summary is None:
        return None
    reports = _node_reports(run, node_id)
    for report in reports:
        report["content"] = _read_text(Path(report["path"]))
    official = _official_nodes(_phase_state(run)).get(node_id) or {}
    return {
        **summary,
        "node": _load_json(run / "nodes" / node_id / "node.json"),
        "official": official,
        "reports": reports,
        "history": _node_history(run, node_id, reports),
    }


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


def _safe_segment(value: str) -> bool:
    return bool(value) and "/" not in value and value not in {".", ".."}


def find_run(target_repo: Path, run_id: str) -> Path | None:
    if not _safe_segment(run_id):
        return None
    run = ai_root(target_repo) / "runs" / run_id
    return run if run.is_dir() else None


def find_node(run: Path, node_id: str) -> Path | None:
    if not _safe_segment(node_id):
        return None
    node = run / "nodes" / node_id
    return node if node.is_dir() else None

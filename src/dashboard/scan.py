"""Scan a target repo's `.ai-scientist/` tree into plain JSON for the dashboard.

Read-only. Shapes follow `docs/SCHEMA.md`. Every reader tolerates missing files,
wrong types and unparseable lines: a half-written run still shows up with
whatever is parseable, and nothing here raises on a bad artifact.

A request scans one run once (`_scan_run`) and passes the parsed context to the
summary, detail and node functions, so `loop-state.json` and the message box
are each read a single time.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.frontmatter import read_frontmatter, read_status_line
from core.message_box import list_messages
from core.state import ai_root

JOURNAL_TAIL = 50

# Node and work statuses that end a node's life (SCHEMA.md section 3.3).
TERMINAL_STATUSES = {"completed", "cancelled", "failed", "abandoned", "accepted", "rejected"}
# Ideation `run.md` status tokens that mean the run is over.
IDEATION_TERMINAL_STATUSES = {"complete", "cancelled"}
# Suffixes the files route serves as text.
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".log", ".py", ".csv", ".yaml", ".yml", ".toml"}

# Conventional ledger keys surfaced on a node summary when present.
NODE_FIELDS = ("title", "idea_id", "assignment", "result_ref", "evidence_summary", "next_action", "metrics")


# --- primitive readers -------------------------------------------------------


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Lenient JSONL read: skip lines that are not JSON objects."""
    try:
        lines = path.read_text(errors="replace").splitlines()
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


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _epoch(iso: Any) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _is_file(path: Path | None) -> bool:
    try:
        return bool(path) and path.is_file()
    except OSError:
        return False


# --- paths -------------------------------------------------------------------


def _target_repo(run: Path) -> Path:
    """`runs/<run-id>` lives at `<target>/.ai-scientist/runs/<run-id>`."""
    try:
        return run.resolve().parents[2]
    except IndexError:
        return run


def _resolve_ref(run: Path, ref: Any) -> Path | None:
    """Resolve a path written inside a run (SCHEMA.md conventions).

    Absolute paths are used as is; paths starting with `.ai-scientist/` are
    relative to the target repo; anything else is relative to the run dir.
    """
    ref = _str(ref)
    if ref is None:
        return None
    candidate = Path(ref)
    if candidate.is_absolute():
        return candidate
    if ref.startswith(".ai-scientist/"):
        return _target_repo(run) / ref
    return run / ref


def _resolve_repo_path(run: Path, ref: Any) -> Path | None:
    """Resolve `contract_path`: relative to the target repo, or absolute."""
    ref = _str(ref)
    if ref is None:
        return None
    candidate = Path(ref)
    return candidate if candidate.is_absolute() else _target_repo(run) / ref


def _run_relative(run: Path, path: Path | None) -> str | None:
    """Path relative to the run dir, for the files route; None when outside."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(run.resolve()).as_posix()
    except (ValueError, OSError):
        return None


# --- contracts and ideas -----------------------------------------------------


def _contract_goal(data: Any) -> str | None:
    """Goal from a wrapped or bare contract: `research_contract.goal`, `goal`, `primary_hypothesis`."""
    if not isinstance(data, dict):
        return None
    inner = _dict(data.get("research_contract"))
    for source in (inner, data):
        for key in ("goal", "primary_hypothesis"):
            value = _str(source.get(key))
            if value:
                return value
    return None


def _ideas_list(data: Any) -> list[dict[str, Any]] | None:
    """`ideas.json["ideas"]` when it is a list of objects, else None."""
    ideas = _dict(data).get("ideas")
    if not isinstance(ideas, list):
        return None
    return [i for i in ideas if isinstance(i, dict)]


def _idea_count(path: Path | None) -> int | None:
    """Idea count from an `ideas.json`, or 1 for a single idea file, or None."""
    if not _is_file(path):
        return None
    if path.suffix == ".json":
        ideas = _ideas_list(_load_json(path))
        return len(ideas) if ideas is not None else None
    return 1


# --- nodes -------------------------------------------------------------------


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


def _alive(status: Any) -> bool:
    return isinstance(status, str) and bool(status) and status.lower() not in TERMINAL_STATUSES


def _work_for_node(work: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    out = []
    for work_id, entry in work.items():
        if isinstance(entry, dict) and entry.get("node") == node_id:
            out.append({"work_id": str(work_id), **entry})
    return out


def _node_report_paths(run: Path, ledger: dict[str, Any], work: list[dict[str, Any]]) -> list[tuple[str, Path, str | None]]:
    """Distinct existing report files: (ref as written, resolved path, owning work id)."""
    seen: set[Path] = set()
    out = []
    # Work items first so a report shared with the ledger keeps its owning work id.
    candidates: list[tuple[Any, str | None]] = [(item.get("result_ref"), item["work_id"]) for item in work]
    candidates.append((ledger.get("result_ref"), None))
    for ref, work_id in candidates:
        path = _resolve_ref(run, ref)
        if not _is_file(path):
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append((str(ref), path, work_id))
    return out


def _node_summaries(run: Path, state: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One summary per `state.nodes` entry, in ledger order."""
    raw_nodes = _dict(state.get("nodes"))
    work = _dict(state.get("work"))
    ledgers = {str(k): _dict(v) for k, v in raw_nodes.items()}
    parents = {node_id: _str(ledger.get("parent_node_id")) for node_id, ledger in ledgers.items()}
    depths = _depths(parents)
    out = []
    for node_id, ledger in ledgers.items():
        node_work = _work_for_node(work, node_id)
        summary: dict[str, Any] = {
            "node_id": node_id,
            "status": ledger.get("status"),
            "alive": _alive(ledger.get("status")),
            "parent_node_id": parents[node_id],
            "depth": depths[node_id],
            "updated_at": ledger.get("updated_at"),
        }
        for key in NODE_FIELDS:
            summary[key] = ledger.get(key)
        summary["work"] = node_work
        summary["report_count"] = len(_node_report_paths(run, ledger, node_work))
        summary["pending_messages"] = _pending_count(messages, node_id)
        summary["ledger"] = raw_nodes.get(node_id)
        out.append(summary)
    return out


# --- message box -------------------------------------------------------------


def _messages(run: Path) -> list[dict[str, Any]]:
    """Every readable `message-box/*.json` record, newest first (SCHEMA.md section 3.11)."""
    try:
        records = list_messages(_target_repo(run), run.name)
    except OSError:
        return []
    return list(reversed(records))


def _pending_count(messages: list[dict[str, Any]], node_id: str | None = None) -> int:
    return sum(1 for m in messages if m.get("status") == "pending" and (node_id is None or m.get("node_id") == node_id))


# --- run context -------------------------------------------------------------


def _scan_run(run: Path) -> dict[str, Any]:
    """Parse a run dir once. Everything else reads from this context."""
    loop_state_path = run / "loop-state.json"
    run_md_path = run / "run.md"
    has_loop_state = _is_file(loop_state_path)
    if has_loop_state:
        kind = "research"
    elif _is_file(run_md_path):
        kind = "ideation"
    else:
        kind = "unknown"
    loop_state = _load_json(loop_state_path) if has_loop_state else None
    loop_state_dict = _dict(loop_state)
    state = _dict(loop_state_dict.get("state"))
    config = read_frontmatter(run / "config.md") if kind == "research" else {}
    messages = _messages(run) if kind == "research" else []
    return {
        "run": run,
        "kind": kind,
        "loop_state": loop_state,
        "top": loop_state_dict,
        "state": state,
        "config": config,
        "messages": messages,
        "nodes": _node_summaries(run, state, messages) if kind == "research" else [],
        "mtime": _mtime(loop_state_path) or _mtime(run_md_path) or _mtime(run),
    }


def _research_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    run: Path = ctx["run"]
    top, state, config = ctx["top"], ctx["state"], ctx["config"]
    orchestrator = _dict(state.get("orchestrator"))
    selection = _dict(state.get("selection"))
    baseline = _dict(state.get("baseline"))
    links = _dict(top.get("links"))
    contract_path = _resolve_repo_path(run, config.get("contract_path")) or _resolve_ref(run, links.get("contract"))
    idea_batch = _resolve_ref(run, config.get("idea_batch")) or _resolve_ref(run, links.get("idea_batch"))
    return {
        "run_id": _str(top.get("run_id")) or run.name,
        "path": str(run),
        "active": bool(top.get("active")) if "active" in top else None,
        "phase": top.get("phase") if ctx["loop_state"] is not None else None,
        "phase_status": top.get("phase_status"),
        "run_outcome": top.get("run_outcome"),
        "blocked_reason": top.get("blocked_reason"),
        "updated_at": top.get("updated_at"),
        "links": top.get("links") if isinstance(top.get("links"), dict) else None,
        "next_action": orchestrator.get("next_action"),
        "selection_status": selection.get("status"),
        "selected_node": selection.get("selected_node"),
        "baseline_status": baseline.get("status"),
        "primary_metric": config.get("primary_metric"),
        "primary_metric_direction": config.get("primary_metric_direction"),
        "success_threshold": config.get("success_threshold"),
        "contract_path": config.get("contract_path"),
        "idea_batch": config.get("idea_batch"),
        "goal": _contract_goal(_load_json(contract_path)) if contract_path else None,
        "idea_count": _idea_count(idea_batch),
        "node_count": len(ctx["nodes"]),
        "pending_messages": _pending_count(ctx["messages"]),
        "mtime": ctx["mtime"],
    }


def _ideation_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    run: Path = ctx["run"]
    status = read_status_line(run / "run.md")
    return {
        **_empty_summary(run, ctx["mtime"]),
        "phase": "ideation",
        "phase_status": status,
        "active": (status.lower() not in IDEATION_TERMINAL_STATUSES) if status else None,
        "goal": _contract_goal(_load_json(run / "contract.json")),
        "idea_count": _idea_count(run / "ideas.json"),
        "node_count": 0,
        "pending_messages": 0,
    }


def _empty_summary(run: Path, mtime: float | None) -> dict[str, Any]:
    return {
        "run_id": run.name,
        "path": str(run),
        "active": None,
        "phase": None,
        "phase_status": None,
        "run_outcome": None,
        "blocked_reason": None,
        "updated_at": None,
        "links": None,
        "next_action": None,
        "selection_status": None,
        "selected_node": None,
        "baseline_status": None,
        "primary_metric": None,
        "primary_metric_direction": None,
        "success_threshold": None,
        "contract_path": None,
        "idea_batch": None,
        "goal": None,
        "idea_count": None,
        "node_count": 0,
        "pending_messages": 0,
        "mtime": mtime,
    }


def _summary(ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx["kind"] == "research":
        return _research_summary(ctx)
    if ctx["kind"] == "ideation":
        return _ideation_summary(ctx)
    return _empty_summary(ctx["run"], ctx["mtime"])


def run_summary(run: Path) -> dict[str, Any]:
    return _summary(_scan_run(run))


# --- run detail --------------------------------------------------------------


def _report_entry(run: Path, path: Path) -> dict[str, Any]:
    return {"path": _run_relative(run, path) or path.name, "name": path.name, "updated_at": _mtime(path)}


def _run_reports(run: Path) -> list[dict[str, Any]]:
    """Every `*.md` directly under the run dir and directly under `logs/` (not recursive)."""
    out = []
    for base in (run, run / "logs"):
        try:
            files = sorted(p for p in base.iterdir() if p.is_file() and p.suffix == ".md")
        except OSError:
            continue
        out.extend(_report_entry(run, p) for p in files)
    return out


def _baseline(run: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    ledger = state.get("baseline") if isinstance(state.get("baseline"), dict) else None
    manifest = _load_json(run / "baseline" / "baseline.json")
    if ledger is None and manifest is None:
        return None
    return {"state": ledger, "manifest": manifest if isinstance(manifest, dict) else None}


def run_detail(run: Path) -> dict[str, Any]:
    ctx = _scan_run(run)
    summary = _summary(ctx)
    state, top = ctx["state"], ctx["top"]
    orchestrator = _dict(state.get("orchestrator"))
    journal = _load_jsonl(run / "journal.jsonl")
    detail: dict[str, Any] = {
        **summary,
        "nodes": ctx["nodes"],
        "work": state.get("work") if isinstance(state.get("work"), dict) else None,
        "resources": state.get("resources"),
        "resource_queue": state.get("resource_queue"),
        "open_questions": orchestrator.get("open_questions"),
        "baseline": _baseline(run, state),
        "selection": _load_json(run / "selection.json"),
        "journal": journal[-JOURNAL_TAIL:],
        "journal_count": len(journal),
        "messages": ctx["messages"],
        "reports": _run_reports(run),
        "loop_state": ctx["loop_state"],
        "config": ctx["config"] or None,
        "run_md": None,
        "ideas": None,
    }
    if ctx["kind"] == "ideation":
        detail["run_md"] = _read_text(run / "run.md")
        detail["ideas"] = _ideas_list(_load_json(run / "ideas.json"))
    return detail


# --- node detail -------------------------------------------------------------


def _node_history(run: Path, node_id: str, work: list[dict[str, Any]], reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chronological trail: journal records for the node, its work entries, and its report files."""
    events: list[dict[str, Any]] = []
    for rec in _load_jsonl(run / "journal.jsonl"):
        if rec.get("node_id") != node_id:
            continue
        events.append(
            {
                "kind": "journal",
                "event_type": rec.get("event_type"),
                "timestamp": rec.get("timestamp"),
                "epoch": _epoch(rec.get("timestamp")),
                "transition_id": rec.get("transition_id"),
                "subagent_id": rec.get("subagent_id"),
                "details": rec.get("details") if isinstance(rec.get("details"), dict) else {},
            }
        )
    for item in work:
        timestamp = _str(item.get("closed_at")) or _str(item.get("updated_at"))
        events.append(
            {
                "kind": "work",
                "work_id": item["work_id"],
                "status": item.get("status"),
                "timestamp": timestamp,
                "epoch": _epoch(timestamp),
                "details": {k: v for k, v in item.items() if k != "work_id"},
            }
        )
    for report in reports:
        events.append(
            {
                "kind": "report",
                "path": report["path"],
                "name": report["name"],
                "work_id": report["work_id"],
                "timestamp": _iso(report["updated_at"]),
                "epoch": report["updated_at"],
            }
        )
    # Events without a usable time (for example still-open work) go last.
    events.sort(key=lambda e: e["epoch"] if e.get("epoch") is not None else float("inf"))
    return events


def node_detail(run: Path, node_id: str) -> dict[str, Any] | None:
    ctx = _scan_run(run)
    summary = next((n for n in ctx["nodes"] if n["node_id"] == node_id), None)
    if summary is None:
        return None
    ledger = _dict(summary.get("ledger"))
    reports = []
    for ref, path, work_id in _node_report_paths(run, ledger, summary["work"]):
        reports.append(
            {
                "ref": ref,
                "path": _run_relative(run, path),
                "name": path.name,
                "work_id": work_id,
                "updated_at": _mtime(path),
                "content": _read_text(path),
            }
        )
    return {
        **summary,
        "reports": reports,
        "messages": [m for m in ctx["messages"] if m.get("node_id") == node_id],
        "history": _node_history(run, node_id, summary["work"], reports),
    }


# --- overview ----------------------------------------------------------------


def _contracts(root: Path) -> list[dict[str, Any]]:
    contracts_dir = root / "contracts"
    try:
        dirs = sorted(p for p in contracts_dir.iterdir() if p.is_dir())
    except OSError:
        return []
    out = []
    for d in dirs:
        data = _load_json(d / "research-contract.json")
        contract = _dict(data).get("research_contract")
        out.append({"contract_id": d.name, "goal": _contract_goal(data), "valid": isinstance(contract, dict)})
    return out


def scan_overview(target_repo: Path) -> dict[str, Any]:
    root = ai_root(target_repo)
    runs_dir = root / "runs"
    runs = []
    try:
        run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    except OSError:
        run_dirs = []
    runs = [run_summary(p) for p in run_dirs]
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


# --- lookups used by the server ---------------------------------------------


def _safe_segment(value: str) -> bool:
    return bool(value) and "/" not in value and value not in {".", ".."}


def find_run(target_repo: Path, run_id: str) -> Path | None:
    if not _safe_segment(run_id):
        return None
    run = ai_root(target_repo) / "runs" / run_id
    return run if run.is_dir() else None


def find_run_file(run: Path, relative: str) -> Path | None:
    """A text file inside the run dir, or None when the path escapes the run or is not a text file.

    Returns the resolved path even when the file is missing so the caller can
    distinguish 404 (missing) from a rejected path.
    """
    if not relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        return None
    candidate = (run / relative).resolve()
    try:
        candidate.relative_to(run.resolve())
    except ValueError:
        return None
    if candidate.suffix.lower() not in TEXT_SUFFIXES:
        return None
    return candidate

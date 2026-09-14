#!/usr/bin/env python3
"""Fail-closed validator for AI Scientist run artifacts.

The shapes checked here are defined in docs/SCHEMA.md. The JSON files under
`schemas/` carry the same required keys and closed enums; `schema_problems`
applies them with a small in-tree checker so the two never drift apart.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.frontmatter import read_frontmatter
from core.plugin import plugin_root
from core.state import (
    JOURNAL_EVENT_TYPES,
    TERMINAL_PHASE_STATUSES,
    active_lease_ids,
    evaluate_completion,
    is_terminal_status,
    open_resource_queue_ids,
)

REQUIRED_CONFIG_KEYS = ("run_id", "contract_path", "idea_batch", "primary_metric", "success_threshold")
LOOP_STATE_REQUIRED = ("run_id", "phase", "phase_status", "active", "updated_at", "state")
LOOP_STATE_PHASES = ("research", "review", "writeup")
LOOP_STATE_PHASE_STATUSES = ("running", *sorted(TERMINAL_PHASE_STATUSES))
WORK_REQUIRED = ("status", "agent_thread_id", "result_ref", "node")
NODE_REQUIRED = ("status", "updated_at")
JOURNAL_REQUIRED = ("event_type", "timestamp", "run_id", "details")
SELECTION_REQUIRED = ("run_id", "status", "selected_node", "acceptance_rationale")
ACTIVE_RUN_REQUIRED = ("run_id", "phase", "status", "updated_at", "target_repository")
REVIEW_DECISIONS = {"accept", "revise", "reject", "negative-result"}
REVIEW_REQUIRED = ("verdict", "leakage", "split_integrity", "baseline_comparison")


class ValidationError(Exception):
    pass


def load_json(path: Path) -> Any:
    if not path.exists():
        raise ValidationError(f"missing required JSON: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON {path}: {exc}") from exc


def ai_root(target: Path) -> Path:
    target = target.resolve()
    candidate = target if target.name == ".ai-scientist" else target / ".ai-scientist"
    if not candidate.exists():
        raise ValidationError(f"missing .ai-scientist directory under {target}")
    return candidate


def pick_run(root: Path, run_id: str | None) -> Path:
    runs = root / "runs"
    if not runs.exists():
        raise ValidationError(f"missing runs directory: {runs}")
    if run_id:
        run = runs / run_id
        if not run.exists():
            raise ValidationError(f"missing requested run: {run}")
        return run
    candidates = sorted(p for p in runs.iterdir() if p.is_dir())
    if not candidates:
        raise ValidationError(f"no run directories under {runs}")
    return candidates[0]


# --- schemas/*.json -----------------------------------------------------------------------------

_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def load_schema(name: str) -> dict[str, Any] | None:
    path = plugin_root() / "schemas" / f"{name}.schema.json"
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _type_matches(value: Any, type_name: str) -> bool:
    if type_name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    expected = _JSON_TYPES.get(type_name)
    if expected is None:
        return True
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected) and not (expected is int and isinstance(value, bool))


def schema_problems(value: Any, schema: dict[str, Any], label: str, path: str = "$") -> list[str]:
    """Check `required`, `type`, `const`, `enum`, `properties`, and `additionalProperties` (the subset the schemas use)."""
    problems: list[str] = []
    declared = schema.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        if not any(_type_matches(value, str(name)) for name in types):
            problems.append(f"{label}: {path} must be of type {'/'.join(map(str, types))}")
            return problems
    if "const" in schema and value != schema["const"]:
        problems.append(f"{label}: {path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{label}: {path} must be one of {', '.join(map(str, schema['enum']))} (got {value!r})")
    if not isinstance(value, dict):
        return problems
    for key in schema.get("required", []):
        if key not in value:
            problems.append(f"{label}: {path} missing required key {key}")
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for key, subschema in properties.items():
        if key in value and isinstance(subschema, dict):
            problems.extend(schema_problems(value[key], subschema, label, f"{path}.{key}"))
    extra = schema.get("additionalProperties")
    if isinstance(extra, dict):
        for key, item in value.items():
            if key not in properties:
                problems.extend(schema_problems(item, extra, label, f"{path}.{key}"))
    return problems


def _require_keys(value: Any, keys: tuple[str, ...], label: str, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}: {path} must be of type object"]
    return [f"{label}: {path} missing required key {key}" for key in keys if key not in value]


def _dedupe(problems: list[str]) -> list[str]:
    return list(dict.fromkeys(problems))


# --- loop-state.json + companions ----------------------------------------------------------------

def read_journal(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse every line of journal.jsonl; unparseable or non-object lines are reported, not skipped."""
    records: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.exists():
        return records, [f"journal.jsonl: missing {path}"]
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"journal.jsonl: line {number} is not valid JSON ({exc.msg})")
            continue
        if not isinstance(value, dict):
            problems.append(f"journal.jsonl: line {number} must be a JSON object")
            continue
        records.append(value)
    return records, problems


def journal_problems(records: list[dict[str, Any]], run_id: str) -> list[str]:
    problems: list[str] = []
    schema = load_schema("journal")
    for index, record in enumerate(records, start=1):
        label = f"journal.jsonl record {index}"
        problems.extend(_require_keys(record, JOURNAL_REQUIRED, label, "$"))
        if schema:
            problems.extend(schema_problems(record, schema, label))
        if record.get("event_type") not in JOURNAL_EVENT_TYPES:
            problems.append(f"{label}: $.event_type must be one of {', '.join(sorted(JOURNAL_EVENT_TYPES))} (got {record.get('event_type')!r})")
        if not isinstance(record.get("details"), dict):
            problems.append(f"{label}: $.details must be of type object")
        if record.get("event_type") == "state_transition" and not isinstance(record.get("transition_id"), str):
            problems.append(f"{label}: state_transition records require transition_id")
        if isinstance(record.get("run_id"), str) and record["run_id"] != run_id:
            problems.append(f"{label}: $.run_id {record['run_id']!r} does not match run {run_id!r}")
    return _dedupe(problems)


def journal_has_transition_id(records: list[dict[str, Any]], transition_id: str) -> bool:
    for record in records:
        if record.get("transition_id") == transition_id:
            return True
        details = record.get("details") if isinstance(record.get("details"), dict) else {}
        if details.get("transition_id") == transition_id:
            return True
    return False


def loop_state_problems(state: Any, run_id: str) -> list[str]:
    label = "loop-state.json"
    problems: list[str] = []
    if not isinstance(state, dict):
        return [f"{label}: $ must be of type object"]
    problems.extend(_require_keys(state, LOOP_STATE_REQUIRED, label, "$"))
    schema = load_schema("loop-state")
    if schema:
        problems.extend(schema_problems(state, schema, label))
    if "run_id" in state and state.get("run_id") != run_id:
        problems.append(f"{label}: $.run_id {state.get('run_id')!r} does not match run directory {run_id!r}")
    phase = state.get("phase")
    if "phase" in state and phase not in LOOP_STATE_PHASES:
        problems.append(f"{label}: $.phase must be one of {', '.join(LOOP_STATE_PHASES)} (got {phase!r})")
    phase_status = state.get("phase_status")
    if "phase_status" in state and phase_status not in LOOP_STATE_PHASE_STATUSES:
        problems.append(f"{label}: $.phase_status must be one of {', '.join(LOOP_STATE_PHASE_STATUSES)} (got {phase_status!r})")
    active = state.get("active")
    if "active" in state and not isinstance(active, bool):
        problems.append(f"{label}: $.active must be of type boolean")
    elif phase_status in TERMINAL_PHASE_STATUSES and active is True:
        problems.append(f"{label}: $.active must be false once phase_status is terminal ({phase_status})")
    elif phase_status == "running" and active is False:
        problems.append(f"{label}: $.active must be true while phase_status is running")
    if phase_status == "blocked" and not (isinstance(state.get("blocked_reason"), str) and state["blocked_reason"].strip()):
        problems.append(f"{label}: $.blocked_reason is required when phase_status is blocked")
    if "last_transition_id" in state and state["last_transition_id"] is not None and not isinstance(state["last_transition_id"], str):
        problems.append(f"{label}: $.last_transition_id must be a string when set")

    phase_state = state.get("state")
    if not isinstance(phase_state, dict):
        if "state" in state:
            problems.append(f"{label}: $.state must be of type object")
        return _dedupe(problems)
    if "orchestrator" in phase_state:
        problems.extend(_require_keys(phase_state["orchestrator"], ("next_action",), label, "$.state.orchestrator"))
    if "baseline" in phase_state:
        problems.extend(_require_keys(phase_state["baseline"], ("status",), label, "$.state.baseline"))
    nodes = phase_state.get("nodes")
    if "nodes" in phase_state:
        if not isinstance(nodes, dict):
            problems.append(f"{label}: $.state.nodes must be of type object")
        else:
            for node_id, node in nodes.items():
                problems.extend(_require_keys(node, NODE_REQUIRED, label, f"$.state.nodes.{node_id}"))
                if isinstance(node, dict):
                    parent = node.get("parent_node_id")
                    if isinstance(parent, str) and parent not in nodes:
                        problems.append(f"{label}: $.state.nodes.{node_id}.parent_node_id {parent!r} is not a node")
    work = phase_state.get("work")
    if "work" in phase_state:
        if not isinstance(work, dict):
            problems.append(f"{label}: $.state.work must be of type object")
        else:
            for work_id, record in work.items():
                problems.extend(_require_keys(record, WORK_REQUIRED, label, f"$.state.work.{work_id}"))
                if isinstance(record, dict):
                    node = record.get("node")
                    if node is not None and not isinstance(node, str):
                        problems.append(f"{label}: $.state.work.{work_id}.node must be a node id or null")
                    elif isinstance(node, str) and isinstance(nodes, dict) and node not in nodes:
                        problems.append(f"{label}: $.state.work.{work_id}.node {node!r} is not a node")
    if "selection" in phase_state:
        selection = phase_state["selection"]
        problems.extend(_require_keys(selection, ("status", "selected_node"), label, "$.state.selection"))
        if isinstance(selection, dict):
            if "status" in selection and selection["status"] not in ("pending", "final"):
                problems.append(f"{label}: $.state.selection.status must be one of pending, final (got {selection['status']!r})")
            selected = selection.get("selected_node")
            if isinstance(selected, str) and isinstance(nodes, dict) and selected not in nodes:
                problems.append(f"{label}: $.state.selection.selected_node {selected!r} is not a node")
    return _dedupe(problems)


def selection_file_problems(selection: Any, state: dict[str, Any], run_id: str) -> list[str]:
    label = "selection.json"
    problems = _require_keys(selection, SELECTION_REQUIRED, label, "$")
    schema = load_schema("selection")
    if schema:
        problems.extend(schema_problems(selection, schema, label))
    if not isinstance(selection, dict):
        return _dedupe(problems)
    if "status" in selection and selection["status"] != "final":
        problems.append(f"{label}: $.status must be final")
    if "run_id" in selection and selection["run_id"] != run_id:
        problems.append(f"{label}: $.run_id {selection['run_id']!r} does not match run {run_id!r}")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    state_selection = phase_state.get("selection") if isinstance(phase_state.get("selection"), dict) else {}
    if state_selection.get("status") == "final" and selection.get("selected_node") != state_selection.get("selected_node"):
        problems.append(f"{label}: $.selected_node {selection.get('selected_node')!r} differs from loop-state selection {state_selection.get('selected_node')!r}")
    return _dedupe(problems)


def active_run_problems(active: Any, run_id: str) -> list[str]:
    label = "active-run.json"
    problems = _require_keys(active, ACTIVE_RUN_REQUIRED, label, "$")
    schema = load_schema("active-run")
    if schema:
        problems.extend(schema_problems(active, schema, label))
    if isinstance(active, dict) and active.get("run_id") == run_id:
        target = active.get("target_repository")
        if isinstance(target, str) and not Path(target).is_absolute():
            problems.append(f"{label}: $.target_repository must be an absolute path")
    return _dedupe(problems)


def validate_loop_state_run(root: Path, run: Path) -> list[str]:
    """Every problem with a research run's loop-state.json and its companions; empty when the run is well-formed."""
    run_id = run.name
    state_path = run / "loop-state.json"
    if not state_path.exists():
        return [f"loop-state.json: missing {state_path}"]
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"loop-state.json: invalid JSON ({exc.msg} at line {exc.lineno})"]
    problems = loop_state_problems(state, run_id)
    records, journal_read_problems = read_journal(run / "journal.jsonl")
    problems.extend(journal_read_problems)
    problems.extend(journal_problems(records, run_id))
    if isinstance(state, dict):
        transition_id = state.get("last_transition_id")
        if isinstance(transition_id, str) and transition_id and not journal_has_transition_id(records, transition_id):
            problems.append(f"loop-state.json: last_transition_id {transition_id!r} has no matching journal.jsonl record")
        selection_path = run / "selection.json"
        if selection_path.exists():
            try:
                selection = json.loads(selection_path.read_text())
            except json.JSONDecodeError as exc:
                problems.append(f"selection.json: invalid JSON ({exc.msg})")
            else:
                problems.extend(selection_file_problems(selection, state, run_id))
    problems.extend(message_box_problems(run))
    active_path = root / "active-run.json"
    if active_path.exists():
        try:
            active = json.loads(active_path.read_text())
        except json.JSONDecodeError as exc:
            problems.append(f"active-run.json: invalid JSON ({exc.msg})")
        else:
            if isinstance(active, dict) and active.get("run_id") == run_id:
                problems.extend(active_run_problems(active, run_id))
    return _dedupe(problems)


def message_box_problems(run: Path) -> list[str]:
    """Every malformed file under message-box/ (docs/SCHEMA.md section 3.11)."""
    box = run / "message-box"
    if not box.is_dir():
        return []
    schema = load_schema("message")
    problems: list[str] = []
    for path in sorted(box.glob("*.json")):
        label = f"message-box/{path.name}"
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            problems.append(f"{label}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(data, dict):
            problems.append(f"{label}: must be a JSON object")
            continue
        if schema:
            problems.extend(schema_problems(data, schema, label))
        if data.get("id") != path.stem:
            problems.append(f"{label}: $.id must equal the file name ({data.get('id')!r})")
        if data.get("run_id") != run.name:
            problems.append(f"{label}: $.run_id must be {run.name!r}")
    return problems


# --- config.md ------------------------------------------------------------------------------------

def target_repository(root: Path) -> Path:
    return root.parent


def contract_object(value: Any) -> dict[str, Any]:
    """Accept the wrapped `{"research_contract": {...}}` form or a bare object (docs/SCHEMA.md section 3.2)."""
    if isinstance(value, dict) and "research_contract" in value:
        inner = value["research_contract"]
        if not isinstance(inner, dict) or not inner:
            raise ValidationError("contract research_contract must be a non-empty object")
        return inner
    if not isinstance(value, dict) or not value:
        raise ValidationError("contract must be a JSON object")
    return value


def check_config(root: Path, run: Path) -> dict[str, Any]:
    cfg_path = run / "config.md"
    if not cfg_path.exists():
        raise ValidationError(f"missing required config.md: {cfg_path}")
    cfg = read_frontmatter(cfg_path)
    if not cfg:
        raise ValidationError(f"config.md has no YAML frontmatter: {cfg_path}")
    missing = [key for key in REQUIRED_CONFIG_KEYS if cfg.get(key) is None or cfg.get(key) == ""]
    if missing:
        raise ValidationError(f"config.md frontmatter missing fields: {', '.join(missing)}")
    if cfg.get("run_id") != run.name:
        raise ValidationError(f"config.md run_id {cfg.get('run_id')!r} does not match run directory {run.name!r}")
    if isinstance(cfg.get("success_threshold"), bool) or not isinstance(cfg.get("success_threshold"), int | float):
        raise ValidationError("config.md success_threshold must be a number")
    contract_path = Path(str(cfg["contract_path"]))
    if not contract_path.is_absolute():
        contract_path = target_repository(root) / contract_path
    if not contract_path.exists():
        raise ValidationError(f"config.md contract_path does not exist: {contract_path}")
    cfg["research_contract"] = contract_object(load_json(contract_path))
    cfg["resolved_contract_path"] = str(contract_path)
    return cfg


# --- gates ----------------------------------------------------------------------------------------

def check_loop_completion(root: Path, run: Path, expected_phase: str) -> None:
    result = evaluate_completion(root, run.name, expected_phase)
    if not result.complete:
        raise ValidationError(f"loop-state.json is not complete for {expected_phase}: {result.reason}")
    state = result.state or {}
    if state.get("phase") != expected_phase:
        raise ValidationError(f"loop-state.json phase must be {expected_phase}")


def check_loop_state_shape(root: Path, run: Path) -> dict[str, Any]:
    problems = validate_loop_state_run(root, run)
    if problems:
        raise ValidationError("loop-state.json is malformed: " + "; ".join(problems))
    return load_json(run / "loop-state.json")


def check_research_loop_state(root: Path, run: Path) -> None:
    check_config(root, run)
    loop_state = check_loop_state_shape(root, run)
    if loop_state.get("phase") != "research":
        raise ValidationError("loop-state.json phase must be research")
    phase_state = loop_state.get("state")
    if not isinstance(phase_state, dict):
        raise ValidationError("loop-state.json state must be an object")
    for section in ("work", "tasks"):
        items = phase_state.get(section) if isinstance(phase_state.get(section), dict) else {}
        for item_id, item in items.items():
            if not isinstance(item, dict):
                raise ValidationError(f"{section} state must be object: {item_id}")
            if not is_terminal_status(item.get("status")):
                raise ValidationError(f"unresolved {section} item blocks research_to_review: {item_id}:{item.get('status')}")
    leases = active_lease_ids(phase_state)
    if leases:
        raise ValidationError(f"active resource leases block research_to_review: {', '.join(leases)}")
    open_queue = open_resource_queue_ids(phase_state)
    if open_queue:
        raise ValidationError(f"resource queue blocks research_to_review: {', '.join(open_queue)}")
    nodes = phase_state.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValidationError("loop-state.json must contain at least one node")
    selection_state = phase_state.get("selection")
    if not isinstance(selection_state, dict) or selection_state.get("status") != "final":
        raise ValidationError("loop-state.json selection must be final")
    selected_node = selection_state.get("selected_node")
    if not isinstance(selected_node, str) or not selected_node:
        raise ValidationError("loop-state.json selection.selected_node is required")
    if selected_node not in nodes:
        raise ValidationError("selected node is missing from loop-state nodes")
    selected = nodes[selected_node]
    if not isinstance(selected, dict):
        raise ValidationError("selected node state must be an object")
    if selected.get("status") != "accepted":
        raise ValidationError("selected node must be accepted")
    if (run / "selection.json").exists():
        selection = load_json(run / "selection.json")
        if selection.get("status") != "final" or selection.get("selected_node") != selected_node:
            raise ValidationError("selection.json must finalize the selected node")
    check_loop_completion(root, run, "research")


def check_research_to_review(root: Path, run: Path) -> None:
    check_research_loop_state(root, run)


def check_review_to_writeup(root: Path, run: Path) -> None:
    check_config(root, run)
    review = load_json(run / "review" / "structured-review.json")
    if not isinstance(review, dict):
        raise ValidationError("structured review must be a JSON object")
    missing = [key for key in REVIEW_REQUIRED if key not in review]
    if missing:
        raise ValidationError(f"structured review missing {', '.join(missing)}")
    verdict = review.get("verdict")
    decision = verdict.get("decision") if isinstance(verdict, dict) else verdict
    if decision not in REVIEW_DECISIONS:
        raise ValidationError(f"structured review verdict.decision must be one of {', '.join(sorted(REVIEW_DECISIONS))}")
    if decision in {"reject", "negative-result"}:
        raise ValidationError(f"{decision} review blocks positive writeup")
    for key in ("leakage", "split_integrity", "baseline_comparison"):
        check = review.get(key)
        if isinstance(check, dict) and "pass" in check and not isinstance(check["pass"], bool):
            raise ValidationError(f"structured review {key}.pass must be a boolean")


def check_writeup_artifacts(run: Path) -> None:
    manifest = load_json(run / "writeup" / "manifest.json")
    report_md = manifest.get("report_md")
    report_tex = manifest.get("report_tex")
    if not isinstance(report_md, str) or not report_md.strip():
        raise ValidationError("writeup manifest must include report_md")
    if not isinstance(report_tex, str) or not report_tex.strip():
        raise ValidationError("writeup manifest must include report_tex")
    md_path = run / report_md
    tex_path = run / report_tex
    if not md_path.exists():
        raise ValidationError(f"writeup markdown report is missing: {report_md}")
    if not tex_path.exists():
        raise ValidationError(f"writeup latex report is missing: {report_tex}")
    if manifest.get("disclosure_present") is not True:
        raise ValidationError("writeup manifest must confirm AI Scientist disclosure")
    if manifest.get("limitations_present") is not True:
        raise ValidationError("writeup manifest must confirm limitations")
    figures = manifest.get("figures")
    if not isinstance(figures, list) or not figures:
        raise ValidationError("writeup manifest must include at least one figure")
    md_text = md_path.read_text()
    tex_text = tex_path.read_text()
    for figure in figures:
        if not isinstance(figure, dict) or not isinstance(figure.get("path"), str):
            raise ValidationError("each writeup figure must include a path")
        figure_path = figure["path"]
        if not (run / figure_path).exists():
            raise ValidationError(f"writeup figure is missing: {figure_path}")
        if figure_path not in md_text and Path(figure_path).name not in tex_text:
            raise ValidationError(f"writeup report does not reference figure: {figure_path}")
    if manifest.get("require_pdf") is not False:
        report_pdf = manifest.get("report_pdf")
        if not isinstance(report_pdf, str) or not report_pdf.strip():
            raise ValidationError("writeup manifest must include report_pdf when require_pdf is true")
        if not (run / report_pdf).exists():
            raise ValidationError(f"writeup PDF report is missing: {report_pdf}")
    audit = load_json(run / "writeup" / "audit" / "final-audit.json")
    if audit.get("verdict") != "ACCEPT":
        raise ValidationError("writeup final audit verdict must be ACCEPT")


def check_launch(run: Path) -> None:
    check_writeup_artifacts(run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="target repo, fixture root, or .ai-scientist directory")
    parser.add_argument("--gate", choices=["research_to_review", "review_to_writeup", "launch"], required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        root = ai_root(args.target)
        run = pick_run(root, args.run_id)
        if args.gate == "research_to_review":
            check_research_to_review(root, run)
        if args.gate == "review_to_writeup":
            check_review_to_writeup(root, run)
        if args.gate == "launch":
            check_launch(run)
    except ValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: {args.gate} validation succeeded for {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

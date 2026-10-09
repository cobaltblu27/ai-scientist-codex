"""`ai-scientist research frontier`: per-node search scores computed from the node ledger.

Read-only. It turns `state.nodes[*].metrics` (docs/SCHEMA.md section 3.3) into the numbers a
UCT-style expansion choice needs; the orchestrator still makes the choice.

- q: best full-fidelity primary metric in the node's subtree, scaled so the reference is 0 and
  the success threshold is 1.
- visits: measured full-fidelity nodes in the subtree, the node included.
- child_cap: ceil(sqrt(visits)); a node earns breadth through measured depth (progressive widening).
- bonus: exploration * sqrt(ln(1 + measured nodes in the run) / (1 + children)).
"""
from __future__ import annotations

import argparse
import math
import statistics
from typing import Any

from cli.response import emit
from core.frontmatter import read_frontmatter
from core.state import config_md_path
from research.workflow import active_run, phase_state_or_error, target_repo

DEFAULT_EXPLORATION = 0.3
DIRECTIONS = {"higher_is_better": 1.0, "lower_is_better": -1.0}
# A rejected node's result is invalid evidence; these statuses also end a node's eligibility to expand.
INVALID_STATUSES = {"rejected"}
CLOSED_STATUSES = {"rejected", "cancelled", "abandoned"}


class FrontierError(Exception):
    pass


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def full_value(node: dict[str, Any], metric: str) -> float | None:
    metrics = node.get("metrics")
    if not isinstance(metrics, dict) or metrics.get("fidelity") != "full":
        return None
    if str(node.get("status", "")).lower() in INVALID_STATUSES:
        return None
    return _number(metrics.get(metric))


def compute_frontier(nodes: dict[str, Any], config: dict[str, Any], exploration: float | None = None) -> dict[str, Any]:
    metric = config.get("primary_metric")
    if not isinstance(metric, str) or not metric:
        raise FrontierError("config.md primary_metric is required")
    direction = config.get("primary_metric_direction")
    if direction not in DIRECTIONS:
        raise FrontierError(f"config.md primary_metric_direction must be one of {', '.join(DIRECTIONS)} (got {direction!r})")
    sign = DIRECTIONS[direction]
    threshold = _number(config.get("success_threshold"))
    if threshold is None:
        raise FrontierError("config.md success_threshold must be a number")
    if exploration is None:
        exploration = _number(config.get("search_exploration"))
    if exploration is None:
        exploration = DEFAULT_EXPLORATION

    entries = {node_id: node for node_id, node in nodes.items() if isinstance(node, dict)}
    children: dict[str, list[str]] = {node_id: [] for node_id in entries}
    for node_id, node in entries.items():
        parent = node.get("parent_node_id")
        if isinstance(parent, str) and parent in children:
            children[parent].append(node_id)
    values = {node_id: full_value(node, metric) for node_id, node in entries.items()}

    reference = _number(config.get("baseline_value"))
    reference_source = "baseline_value"
    if reference is None:
        root_values = [v for node_id, v in values.items() if v is not None and not isinstance(entries[node_id].get("parent_node_id"), str)]
        reference = statistics.median(root_values) if root_values else None
        reference_source = "root_median"
    if reference is not None and sign * (threshold - reference) <= 0:
        raise FrontierError(f"reference {reference} already meets success_threshold {threshold}; scores cannot be scaled")

    def subtree(node_id: str) -> list[str]:
        out, stack = [], [node_id]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(children[current])
        return out

    measured_total = sum(1 for v in values.values() if v is not None)
    candidates, unmeasured = [], []
    for node_id, node in entries.items():
        measured = [values[n] for n in subtree(node_id) if values[n] is not None]
        if not measured:
            unmeasured.append(node_id)
            continue
        best = max(measured, key=lambda v: sign * v)
        q = sign * (best - reference) / (sign * (threshold - reference)) if reference is not None else None
        n_children = len(children[node_id])
        cap = math.ceil(math.sqrt(len(measured)))
        bonus = exploration * math.sqrt(math.log(1 + measured_total) / (1 + n_children))
        status = str(node.get("status", "")).lower()
        candidates.append({
            "node": node_id,
            "status": node.get("status"),
            "value": values[node_id],
            "subtree_best": best,
            "q": None if q is None else round(q, 4),
            "visits": len(measured),
            "children": n_children,
            "child_cap": cap,
            "expandable": status not in CLOSED_STATUSES and n_children < cap,
            "bonus": round(bonus, 4),
            "score": None if q is None else round(q + bonus, 4),
        })
    candidates.sort(key=lambda c: (not c["expandable"], -(c["score"] if c["score"] is not None else float("-inf")), c["node"]))
    return {
        "primary_metric": metric,
        "direction": direction,
        "success_threshold": threshold,
        "reference": {"value": reference, "source": reference_source if reference is not None else None},
        "exploration": exploration,
        "measured_nodes": measured_total,
        "candidates": candidates,
        "unmeasured": sorted(unmeasured),
    }


def cmd_research_frontier(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    phase_state = phase_state_or_error(state, run_id)
    config = read_frontmatter(config_md_path(target, run_id))
    if not config:
        raise FrontierError(f"missing config.md frontmatter for run {run_id}")
    nodes = phase_state.get("nodes") if isinstance(phase_state.get("nodes"), dict) else {}
    return emit("ok", run_id=run_id, **compute_frontier(nodes, config, args.exploration))

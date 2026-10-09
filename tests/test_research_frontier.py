"""`ai-scientist research frontier` scores nodes from the ledger metrics docs/SCHEMA.md defines."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from cli.main import main as cli_main
from research.frontier import FrontierError, compute_frontier
from test_support import write_json

TS = "2026-09-09T18:14:29Z"
CONFIG = {"primary_metric": "acc", "primary_metric_direction": "higher_is_better", "success_threshold": 0.9}


def node(value: float | None = None, parent: str | None = None, status: str = "completed", fidelity: str = "full") -> dict[str, Any]:
    entry: dict[str, Any] = {"status": status, "updated_at": TS, "parent_node_id": parent}
    if value is not None:
        entry["metrics"] = {"acc": value, "n_seeds": 1, "fidelity": fidelity}
    return entry


def by_node(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["node"]: c for c in result["candidates"]}


def test_q_scales_reference_to_zero_and_threshold_to_one() -> None:
    result = compute_frontier({"N1": node(0.7), "N2": node(0.8)}, {**CONFIG, "baseline_value": 0.7})
    rows = by_node(result)
    assert result["reference"] == {"value": 0.7, "source": "baseline_value"}
    assert rows["N1"]["q"] == 0.0
    assert rows["N2"]["q"] == pytest.approx(0.5)


def test_reference_falls_back_to_root_median() -> None:
    result = compute_frontier({"N1": node(0.6), "N2": node(0.7), "N3": node(0.8), "N4": node(0.85, parent="N3")}, CONFIG)
    assert result["reference"] == {"value": 0.7, "source": "root_median"}


def test_lower_is_better_flips_the_sign() -> None:
    config = {"primary_metric": "acc", "primary_metric_direction": "lower_is_better", "success_threshold": 2.0, "baseline_value": 3.0}
    rows = by_node(compute_frontier({"N1": node(2.5), "N2": node(3.5)}, config))
    assert rows["N1"]["q"] == pytest.approx(0.5)
    assert rows["N2"]["q"] == pytest.approx(-0.5)


def test_q_is_best_in_subtree_and_visits_count_measured_descendants() -> None:
    nodes = {"N1": node(0.7), "N2": node(0.85, parent="N1"), "N3": node(None, parent="N1", status="running")}
    rows = by_node(compute_frontier(nodes, {**CONFIG, "baseline_value": 0.7}))
    assert rows["N1"]["subtree_best"] == 0.85
    assert rows["N1"]["visits"] == 2
    assert rows["N1"]["children"] == 2


def test_child_cap_grows_with_measured_depth() -> None:
    nodes = {"N1": node(0.7), "N2": node(0.75, parent="N1")}
    rows = by_node(compute_frontier(nodes, {**CONFIG, "baseline_value": 0.7}))
    # N1: 2 measured in subtree -> cap 2, one child -> still expandable. N2: 1 measured -> cap 1, no children.
    assert rows["N1"]["child_cap"] == 2 and rows["N1"]["expandable"]
    assert rows["N2"]["child_cap"] == 1 and rows["N2"]["expandable"]
    nodes["N3"] = node(None, parent="N1", status="running")
    assert not by_node(compute_frontier(nodes, {**CONFIG, "baseline_value": 0.7}))["N1"]["expandable"]


def test_bonus_shrinks_with_children_and_uses_exploration_weight() -> None:
    nodes = {"N1": node(0.7), "N2": node(0.7), "N3": node(0.7, parent="N1")}
    result = compute_frontier(nodes, {**CONFIG, "baseline_value": 0.6, "search_exploration": 0.5})
    rows = by_node(result)
    assert result["exploration"] == 0.5
    assert rows["N2"]["bonus"] == pytest.approx(0.5 * math.sqrt(math.log(4)), abs=1e-4)
    assert rows["N1"]["bonus"] == pytest.approx(0.5 * math.sqrt(math.log(4) / 2), abs=1e-4)
    assert compute_frontier(nodes, {**CONFIG, "baseline_value": 0.6}, exploration=0.0)["candidates"][0]["bonus"] == 0.0


def test_only_full_fidelity_and_valid_nodes_count() -> None:
    nodes = {"N1": node(0.7), "N2": node(0.95, fidelity="screen"), "N3": node(0.99, status="rejected")}
    result = compute_frontier(nodes, {**CONFIG, "baseline_value": 0.6})
    assert result["measured_nodes"] == 1
    assert result["unmeasured"] == ["N2", "N3"]


def test_closed_nodes_are_listed_but_not_expandable_and_sort_last() -> None:
    nodes = {"N1": node(0.85, status="abandoned"), "N2": node(0.7)}
    result = compute_frontier(nodes, {**CONFIG, "baseline_value": 0.6})
    assert [c["node"] for c in result["candidates"]] == ["N2", "N1"]
    assert not by_node(result)["N1"]["expandable"]


def test_configuration_errors_fail_fast() -> None:
    with pytest.raises(FrontierError, match="primary_metric_direction"):
        compute_frontier({}, {"primary_metric": "acc", "success_threshold": 0.9})
    with pytest.raises(FrontierError, match="already meets"):
        compute_frontier({"N1": node(0.7)}, {**CONFIG, "baseline_value": 0.95})


def test_cli_prints_frontier(tmp_path: Path, capsys) -> None:
    run = tmp_path / ".ai-scientist" / "runs" / "run-1"
    write_json(run / "loop-state.json", {
        "schema_version": 1, "run_id": "run-1", "phase": "research", "phase_status": "running", "active": True, "updated_at": TS,
        "state": {"orchestrator": {"next_action": "x"}, "nodes": {"N1": node(0.7), "N2": node(0.8, parent="N1")}},
    })
    (run / "config.md").write_text("---\nrun_id: run-1\nprimary_metric: acc\nprimary_metric_direction: higher_is_better\nsuccess_threshold: 0.9\nbaseline_value: 0.7\n---\n")
    assert cli_main(["--target-repo", str(tmp_path), "research", "frontier", "--run-id", "run-1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert {c["node"] for c in payload["candidates"]} == {"N1", "N2"}

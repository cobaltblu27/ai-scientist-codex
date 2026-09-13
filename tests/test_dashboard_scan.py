import json
from pathlib import Path

from dashboard.scan import find_run, run_detail, scan_overview


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / ".ai-scientist"
    _write(root / "active-run.json", {"run_id": "run-a", "phase": "research", "status": "active"})
    _write(
        root / "runs/run-a/loop-state.json",
        {
            "run_id": "run-a",
            "active": True,
            "phase": "research",
            "phase_status": "running",
            "updated_at": "2026-09-12T00:00:00Z",
            "completed_phases": {"ideation": {}},
            "state": {"orchestrator": {"next_action": "dispatch", "iteration": 2}, "selected_node": None},
        },
    )
    _write(root / "runs/run-a/config.json", {"research_contract": {"goal": "beat baseline", "metrics": {"primary": "accuracy"}}})
    _write(root / "runs/run-a/nodes/node-1/node.json", {"node_id": "node-1", "status": "running", "metrics": {"accuracy": 0.9}, "trials": [{}]})
    _write(root / "runs/run-a/journal.jsonl", '{"event_type":"x","timestamp":"t","run_id":"run-a","details":{}}\nnot json\n')
    _write(root / "runs/run-b/loop-state.json", "{ broken")
    _write(root / "contracts/c1/research-contract.json", {"research_contract": {"goal": "g"}})
    return tmp_path


def test_overview_lists_runs_and_contracts(tmp_path: Path) -> None:
    target = _fixture(tmp_path)
    overview = scan_overview(target)
    assert overview["exists"] is True
    assert overview["active_run"]["run_id"] == "run-a"
    assert {r["run_id"] for r in overview["runs"]} == {"run-a", "run-b"}
    run_a = next(r for r in overview["runs"] if r["run_id"] == "run-a")
    assert run_a["node_count"] == 1
    assert run_a["goal"] == "beat baseline"
    assert run_a["completed_phases"] == ["ideation"]
    assert overview["contracts"] == [{"contract_id": "c1", "goal": "g", "valid": True}]


def test_detail_tolerates_bad_journal_lines(tmp_path: Path) -> None:
    target = _fixture(tmp_path)
    detail = run_detail(find_run(target, "run-a"))
    assert detail["journal_count"] == 1
    assert detail["nodes"][0]["metrics"] == {"accuracy": 0.9}
    assert detail["next_action"] == "dispatch"


def test_broken_loop_state_still_listed(tmp_path: Path) -> None:
    target = _fixture(tmp_path)
    detail = run_detail(find_run(target, "run-b"))
    assert detail["run_id"] == "run-b"
    assert detail["phase"] is None


def test_find_run_rejects_traversal(tmp_path: Path) -> None:
    target = _fixture(tmp_path)
    assert find_run(target, "../..") is None
    assert find_run(target, "missing") is None


def test_missing_root(tmp_path: Path) -> None:
    overview = scan_overview(tmp_path)
    assert overview["exists"] is False
    assert overview["runs"] == []

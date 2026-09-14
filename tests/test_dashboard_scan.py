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


def _tree_fixture(tmp_path: Path) -> Path:
    root = tmp_path / ".ai-scientist" / "runs" / "run-t"
    _write(
        root / "loop-state.json",
        {
            "run_id": "run-t",
            "active": True,
            "phase": "research",
            "phase_status": "running",
            "updated_at": "2026-09-12T00:00:00Z",
            "state": {
                "orchestrator": {"current_node": "n3"},
                # official ledger: n2's parent lives only here, and n1's official status overrides node.json
                "nodes": {"n1": {"status": "accepted"}, "n2": {"status": "accepted", "parent_node_id": "n1"}},
                "work": {"worker-n3": {"status": "running", "node_id": "n3", "updated_at": "2026-09-12T00:05:00Z"}},
            },
        },
    )
    _write(root / "nodes/n1/node.json", {"node_id": "n1", "status": "running", "metrics": {"accuracy": 0.9}, "trials": []})
    _write(root / "nodes/n2/node.json", {"node_id": "n2", "status": "accepted", "metrics": {}, "trials": []})
    _write(root / "nodes/n3/node.json", {"node_id": "n3", "parent_node_id": "n2", "status": "running", "metrics": {}, "trials": [{}]})
    _write(root / "nodes/n4/node.json", {"node_id": "n4", "parent_node_id": "ghost", "status": "rejected", "metrics": {}, "trials": []})
    _write(root / "logs/workers/n3/worker-n3/result.md", "# n3 plan\n\n- [ ] run it\n")
    _write(root / "logs/revisions/n3/rev-1/result.md", "# revise n3\n")
    _write(root / "logs/workers/n3/incomplete-worker/notes.txt", "not a result.md")
    _write(
        root / "journal.jsonl",
        "\n".join(
            [
                json.dumps({"event_type": "node_created", "timestamp": "2026-09-12T00:01:00Z", "run_id": "run-t", "node_id": "n3", "details": {}}),
                json.dumps({"event_type": "subagent", "timestamp": "2026-09-12T00:02:00Z", "run_id": "run-t", "subagent_id": "worker-n3", "details": {"status": "running"}}),
                json.dumps({"event_type": "subagent", "timestamp": "2026-09-12T00:03:00Z", "run_id": "run-t", "node_id": "n1", "subagent_id": "worker-n1", "details": {}}),
            ]
        )
        + "\n",
    )
    return tmp_path


def test_node_parents_depth_and_official_status(tmp_path: Path) -> None:
    target = _tree_fixture(tmp_path)
    nodes = {n["node_id"]: n for n in run_detail(find_run(target, "run-t"))["nodes"]}
    assert nodes["n1"]["parent_node_id"] is None and nodes["n1"]["depth"] == 0
    assert nodes["n2"]["parent_node_id"] == "n1" and nodes["n2"]["depth"] == 1  # parent from loop-state ledger
    assert nodes["n3"]["parent_node_id"] == "n2" and nodes["n3"]["depth"] == 2  # parent from node.json
    assert nodes["n4"]["parent_node_id"] == "ghost" and nodes["n4"]["depth"] == 0  # unknown parent -> root
    # official status wins over node.json status for liveness
    assert nodes["n1"]["status"] == "running" and nodes["n1"]["official_status"] == "accepted" and nodes["n1"]["alive"] is False
    assert nodes["n3"]["alive"] is True and nodes["n4"]["alive"] is False
    assert nodes["n3"]["report_count"] == 2


def test_node_detail_reports_and_history(tmp_path: Path) -> None:
    from dashboard.scan import node_detail

    target = _tree_fixture(tmp_path)
    run = find_run(target, "run-t")
    detail = node_detail(run, "n3")
    assert detail is not None
    assert [(r["kind"], r["agent_id"]) for r in detail["reports"]] == [("worker", "worker-n3"), ("revision", "rev-1")]
    assert detail["reports"][0]["content"].startswith("# n3 plan")
    kinds = [(e["kind"], e["event_type"], e["agent_id"]) for e in detail["history"]]
    # journal event by node_id, journal event by work id, the work ledger row, and both report files
    assert ("journal", "node_created", None) in kinds
    assert ("journal", "subagent", "worker-n3") in kinds
    assert ("work", "work", "worker-n3") in kinds
    assert ("report", "worker_report", "worker-n3") in kinds
    assert ("report", "revision_report", "rev-1") in kinds
    assert not any(e["agent_id"] == "worker-n1" for e in detail["history"])
    assert node_detail(run, "missing") is None


def test_find_node_rejects_traversal(tmp_path: Path) -> None:
    from dashboard.scan import find_node

    target = _tree_fixture(tmp_path)
    run = find_run(target, "run-t")
    assert find_node(run, "n3") is not None
    assert find_node(run, "../run-t") is None
    assert find_node(run, "") is None


def test_server_routes(tmp_path: Path) -> None:
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen
    from urllib.error import HTTPError

    from dashboard.server import make_handler

    target = _tree_fixture(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(target, tmp_path / "no-dist"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert json.load(urlopen(f"{base}/api/runs/run-t"))["run_id"] == "run-t"
        node = json.load(urlopen(f"{base}/api/runs/run-t/nodes/n3"))
        assert node["node_id"] == "n3" and len(node["reports"]) == 2
        for bad in ("/api/runs/run-t/nodes/nope", "/api/runs/run-t/other/n3", "/api/runs/nope"):
            try:
                urlopen(f"{base}{bad}")
            except HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError(f"{bad} should 404")
        try:
            urlopen(f"{base}/")
        except HTTPError as exc:
            assert exc.code == 503  # frontend not built
    finally:
        server.shutdown()
        server.server_close()

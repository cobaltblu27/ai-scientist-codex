"""Dashboard scanner tests against the SCHEMA.md-shaped fixture in tests/fixtures/dashboard."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dashboard.scan import find_run, find_run_file, node_detail, run_detail, run_summary, scan_overview
from dashboard.server import make_handler
from test_support import REPO_ROOT

FIXTURE_SCRIPT = REPO_ROOT / "tests" / "fixtures" / "dashboard" / "make_fixture.py"


def _load_fixture_module():
    spec = importlib.util.spec_from_file_location("make_fixture", FIXTURE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fx = _load_fixture_module()


@pytest.fixture(scope="module")
def target(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dashboard-target")
    fx.build(out)
    return out


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


# --- overview ----------------------------------------------------------------


def test_overview_lists_every_run_in_order(target: Path) -> None:
    overview = scan_overview(target)
    assert overview["exists"] is True
    assert overview["active_run"]["run_id"] == fx.RESEARCH_RUN
    assert [r["run_id"] for r in overview["runs"]] == [
        fx.BROKEN_RUN,  # no updated_at; newest mtime wins
        fx.RESEARCH_RUN,
        fx.BLOCKED_RUN,
        fx.IDEATION_RUN,  # no updated_at; run.md mtime
        fx.SUCCESS_RUN,
        fx.EXHAUSTED_RUN,
    ]
    contracts = {c["contract_id"]: c for c in overview["contracts"]}
    assert contracts["cifar10-accuracy"]["valid"] is True
    assert contracts["cifar10-accuracy"]["goal"].startswith("Beat the ResNet-18")
    assert contracts["broken-draft"] == {"contract_id": "broken-draft", "goal": None, "valid": False}


def test_overview_research_summary_fields(target: Path) -> None:
    runs = {r["run_id"]: r for r in scan_overview(target)["runs"]}
    live = runs[fx.RESEARCH_RUN]
    assert live["phase"] == "research" and live["phase_status"] == "running" and live["active"] is True
    assert live["next_action"].startswith("read N2-w-002")
    assert live["primary_metric"] == "accuracy"
    assert live["primary_metric_direction"] == "higher_is_better"
    assert live["success_threshold"] == 0.93
    assert live["contract_path"] == ".ai-scientist/contracts/cifar10-accuracy/research-contract.json"
    assert live["goal"] == "Beat the ResNet-18 baseline on CIFAR-10 test accuracy"
    assert live["idea_count"] == 3  # from the ideation run's ideas.json named by idea_batch
    assert live["node_count"] == 5
    assert live["selection_status"] == "pending" and live["selected_node"] is None
    assert live["baseline_status"] == "completed"
    assert live["links"]["discovery_notes"] == "discovery-notes.md"
    for dropped in ("completed_at", "completed_phases", "iteration", "current_node"):
        assert dropped not in live

    success = runs[fx.SUCCESS_RUN]
    assert success["active"] is False and success["phase_status"] == "success" and success["run_outcome"] == "success"
    assert success["selection_status"] == "final" and success["selected_node"] == "N2"

    blocked = runs[fx.BLOCKED_RUN]
    assert blocked["phase_status"] == "blocked"
    assert blocked["blocked_reason"].startswith("dataset mount")

    assert runs[fx.EXHAUSTED_RUN]["phase_status"] == "exhausted"


def test_overview_ideation_run(target: Path) -> None:
    runs = {r["run_id"]: r for r in scan_overview(target)["runs"]}
    ideation = runs[fx.IDEATION_RUN]
    assert ideation["phase"] == "ideation"
    assert ideation["phase_status"] == "complete"
    assert ideation["active"] is False
    assert ideation["goal"] == "Beat the ResNet-18 baseline on CIFAR-10 test accuracy"  # bare contract.json
    assert ideation["idea_count"] == 3
    assert ideation["node_count"] == 0


def test_ideation_without_status_line(tmp_path: Path) -> None:
    run = tmp_path / ".ai-scientist" / "runs" / "ideation-x"
    _write(run / "run.md", "# Run\n\nno status bullet here\n")
    _write(run / "contract.json", {"research_contract": {"goal": "wrapped goal"}})
    summary = run_summary(run)
    assert summary["phase"] == "ideation"
    assert summary["phase_status"] is None and summary["active"] is None
    assert summary["goal"] == "wrapped goal"
    assert summary["idea_count"] is None

    run2 = tmp_path / ".ai-scientist" / "runs" / "ideation-y"
    _write(run2 / "run.md", "- status: running\n")
    assert run_summary(run2)["active"] is True


# --- run detail --------------------------------------------------------------


def test_run_detail_nodes_work_and_reports(target: Path) -> None:
    detail = run_detail(find_run(target, fx.RESEARCH_RUN))
    nodes = {n["node_id"]: n for n in detail["nodes"]}
    assert list(nodes) == ["N1", "N2", "N3", "N4", "N5"]  # ledger order

    assert (nodes["N1"]["parent_node_id"], nodes["N1"]["depth"]) == (None, 0)
    assert (nodes["N2"]["parent_node_id"], nodes["N2"]["depth"]) == ("N1", 1)
    assert (nodes["N3"]["parent_node_id"], nodes["N3"]["depth"]) == ("N1", 1)
    assert (nodes["N4"]["parent_node_id"], nodes["N4"]["depth"]) == ("N2", 2)
    assert (nodes["N5"]["parent_node_id"], nodes["N5"]["depth"]) == (None, 0)

    assert {n: nodes[n]["alive"] for n in nodes} == {"N1": False, "N2": True, "N3": False, "N4": True, "N5": True}

    # work grouped by `node`, run-wide work (node null) attached nowhere
    assert [w["work_id"] for w in nodes["N2"]["work"]] == ["N2-w-001", "N2-w-002"]
    assert nodes["N2"]["work"][1]["status"] == "running"
    assert nodes["N4"]["work"] == []
    assert all("rk-001" not in [w["work_id"] for w in n["work"]] for n in nodes.values())
    assert set(detail["work"]) == {"bl-001", "N1-w-001", "N1-r-002", "N2-w-001", "N2-w-002", "N3-w-001", "N5-w-001", "rk-001"}
    assert nodes["N1"]["work"][1] == {**nodes["N1"]["work"][1], "work_id": "N1-r-002", "kind": "revision", "message_id": fx.MSG_N1_ACK}

    # conventional fields and the raw ledger
    assert nodes["N2"]["title"] == "Snapshot ensemble on N1"
    assert nodes["N2"]["idea_id"] == "snapshot-ensemble"
    assert nodes["N2"]["metrics"] == {"accuracy": 0.936}
    assert nodes["N2"]["result_ref"] == "logs/workers/N2/N2-w-001/result.md"
    assert nodes["N2"]["ledger"]["assignment"].startswith("ensemble three")
    assert nodes["N4"]["metrics"] is None

    # report_count: distinct existing files among node + work result_refs
    assert {n: nodes[n]["report_count"] for n in nodes} == {"N1": 2, "N2": 2, "N3": 1, "N4": 0, "N5": 1}

    # run-level reports: *.md directly under the run dir and directly under logs/
    assert [r["path"] for r in detail["reports"]] == [
        "config.md",
        "discovery-notes.md",
        "learning-notes.md",
        "logs/agent-map.md",
        "logs/resource-log.md",
    ]
    assert detail["reports"][1]["name"] == "discovery-notes.md"
    assert isinstance(detail["reports"][1]["updated_at"], float)

    assert list(detail["open_questions"]) == ["q-seed-variance", "q-tta-cost"]
    assert detail["baseline"]["state"]["status"] == "completed"
    assert detail["baseline"]["manifest"]["fixed_split_dir"].startswith("nodes/baseline")
    assert detail["resources"]["leases"]["lease-1"]["gpu"] == 0
    assert detail["resource_queue"]["pending"] == ["N4-w-001"]
    assert detail["selection"] is None
    assert detail["journal_count"] == 20  # the two garbage lines are skipped
    assert len(detail["journal"]) == 20
    assert detail["loop_state"]["run_id"] == fx.RESEARCH_RUN
    assert detail["config"]["active_node_cap"] == 3
    assert detail["run_md"] is None and detail["ideas"] is None


def test_run_detail_success_and_ideation(target: Path) -> None:
    success = run_detail(find_run(target, fx.SUCCESS_RUN))
    assert success["selection"]["selected_node"] == "N2"
    assert success["selection"]["acceptance_rationale"].startswith("rmse 0.471")
    assert success["baseline"] == {"state": {"status": "not_required"}, "manifest": None}
    assert "completion-audit.md" in [r["path"] for r in success["reports"]]

    ideation = run_detail(find_run(target, fx.IDEATION_RUN))
    assert ideation["run_md"].startswith("# Run:")
    assert [i["id"] for i in ideation["ideas"]] == [i for i, _ in fx.IDEAS]
    assert ideation["ideas"][0]["pilot_report"] == "logs/pilots/mixup-cutout-schedule/report.md"
    assert [r["path"] for r in ideation["reports"]] == ["run.md", "logs/filter.md"]
    assert ideation["nodes"] == [] and ideation["journal"] == [] and ideation["loop_state"] is None
    assert ideation["messages"] == [] and ideation["pending_messages"] == 0


# --- node detail -------------------------------------------------------------


def test_node_detail_history_is_ordered(target: Path) -> None:
    run = find_run(target, fx.RESEARCH_RUN)
    detail = node_detail(run, "N2")
    assert detail is not None
    assert detail["node_id"] == "N2" and detail["depth"] == 1

    history = detail["history"]
    epochs = [h["epoch"] for h in history if h["epoch"] is not None]
    assert epochs == sorted(epochs)
    # still-open work without a timestamp goes last
    assert history[-1] == {**history[-1], "kind": "work", "work_id": "N2-w-002", "epoch": None}

    journal = [h for h in history if h["kind"] == "journal"]
    assert [h["event_type"] for h in journal] == ["state_transition", "state_transition", "finding", "state_transition", "message"]
    assert journal[-1]["details"]["message_id"] == fx.MSG_N2_PENDING
    assert all(h["details"] for h in journal)
    assert not any(h["kind"] == "journal" and h["details"].get("note", "").startswith("N1") for h in history)

    work = [h["work_id"] for h in history if h["kind"] == "work"]
    assert work == ["N2-w-001", "N2-w-002"]
    closed = next(h for h in history if h["kind"] == "work" and h["work_id"] == "N2-w-001")
    assert closed["timestamp"] == fx.ts(40)  # closed_at wins

    reports = [h for h in history if h["kind"] == "report"]
    assert [r["path"] for r in reports] == ["logs/workers/N2/N2-w-001/result.md", "logs/revisions/N2/N2-w-002/result.md"]
    assert reports[0]["timestamp"] == fx.ts(40)  # file mtime
    assert reports[1]["work_id"] == "N2-w-002"

    assert [(r["path"], r["work_id"]) for r in detail["reports"]] == [
        ("logs/workers/N2/N2-w-001/result.md", "N2-w-001"),
        ("logs/revisions/N2/N2-w-002/result.md", "N2-w-002"),
    ]
    assert detail["reports"][0]["content"].startswith("# N2: Snapshot ensemble on N1")

    assert node_detail(run, "N4")["reports"] == []
    assert node_detail(run, "missing") is None
    assert node_detail(run, "../N2") is None


def test_node_detail_missing_report_file(target: Path) -> None:
    detail = node_detail(find_run(target, fx.BLOCKED_RUN), "N2")
    assert detail is not None
    assert detail["result_ref"] == "logs/workers/N2/N2-w-001/result.md"
    assert detail["report_count"] == 0 and detail["reports"] == []
    assert [h["kind"] for h in detail["history"]] == ["journal", "work"]


# --- message box -------------------------------------------------------------


MESSAGE_KEYS = {"id", "run_id", "node_id", "kind", "prompt", "created_at", "status", "updated_at", "work_id", "result_node_id", "note"}


def test_run_detail_messages_newest_first(target: Path) -> None:
    detail = run_detail(find_run(target, fx.RESEARCH_RUN))
    messages = detail["messages"]
    assert [m["id"] for m in messages] == [fx.MSG_N2_PENDING, fx.MSG_N1_ACK, fx.MSG_N3_REJECTED]  # the malformed file is skipped
    assert all(set(m) == MESSAGE_KEYS for m in messages)
    assert [m["status"] for m in messages] == ["pending", "acknowledged", "rejected"]
    assert messages[0] == {**messages[0], "node_id": "N2", "kind": "branch", "work_id": None, "result_node_id": None, "note": None}
    assert messages[1]["work_id"] == "N1-r-002" and messages[1]["node_id"] == "N1"
    assert messages[2]["note"].startswith("N3 is failed")
    assert detail["pending_messages"] == 1

    nodes = {n["node_id"]: n for n in detail["nodes"]}
    assert {n: nodes[n]["pending_messages"] for n in nodes} == {"N1": 0, "N2": 1, "N3": 0, "N4": 0, "N5": 0}
    assert "messages" not in nodes["N2"]  # summaries carry the count only


def test_run_summary_pending_messages(target: Path) -> None:
    runs = {r["run_id"]: r for r in scan_overview(target)["runs"]}
    assert runs[fx.RESEARCH_RUN]["pending_messages"] == 1
    assert runs[fx.SUCCESS_RUN]["pending_messages"] == 0
    assert runs[fx.IDEATION_RUN]["pending_messages"] == 0
    assert runs[fx.BROKEN_RUN]["pending_messages"] == 0


def test_node_detail_messages(target: Path) -> None:
    run = find_run(target, fx.RESEARCH_RUN)
    n2 = node_detail(run, "N2")
    assert [m["id"] for m in n2["messages"]] == [fx.MSG_N2_PENDING]
    assert n2["pending_messages"] == 1
    n1 = node_detail(run, "N1")
    assert [m["id"] for m in n1["messages"]] == [fx.MSG_N1_ACK] and n1["pending_messages"] == 0
    assert node_detail(run, "N4")["messages"] == []


# --- tolerance ---------------------------------------------------------------


def test_broken_loop_state_is_listed_with_nulls(target: Path) -> None:
    run = find_run(target, fx.BROKEN_RUN)
    summary = run_summary(run)
    assert summary["run_id"] == fx.BROKEN_RUN
    assert summary["phase"] is None and summary["phase_status"] is None and summary["active"] is None
    assert summary["node_count"] == 0 and summary["goal"] is None
    detail = run_detail(run)
    assert detail["nodes"] == [] and detail["loop_state"] is None and detail["work"] is None
    assert detail["reports"] == [] and detail["journal_count"] == 0
    assert node_detail(run, "N1") is None


def test_wrong_types_never_raise(tmp_path: Path) -> None:
    run = tmp_path / ".ai-scientist" / "runs" / "weird"
    _write(
        run / "loop-state.json",
        {
            "run_id": 7,
            "active": "yes",
            "phase": ["research"],
            "links": "config.md",
            "state": {
                "orchestrator": [],
                "baseline": "ready",
                "nodes": {"A": {"status": "running", "parent_node_id": "B"}, "B": {"status": 3, "parent_node_id": "A"}, "C": "not a dict", "D": {"parent_node_id": ["x"]}},
                "work": {"w1": {"node": "A", "status": "running", "result_ref": ["bad"]}, "w2": "bad", "w3": {"node": "A", "result_ref": "../../../etc/passwd"}},
                "resources": 5,
                "selection": None,
            },
        },
    )
    _write(run / "config.md", "---\nprimary_metric: rmse\ncontract_path: nowhere.json\nidea_batch: [1, 2]\n")  # no closing fence
    _write(run / "journal.jsonl", '{"node_id": "A", "timestamp": 5}\n[1,2]\n{"event_type": "note", "node_id": "A", "timestamp": "2026-01-01T00:00:00Z", "details": "text"}\n')
    _write(run / "baseline" / "baseline.json", "[]")
    _write(run / "selection.json", "{")

    summary = run_summary(run)
    assert summary["run_id"] == "weird"  # non-string run_id falls back to the dir name
    assert summary["phase"] == ["research"] and summary["links"] is None
    assert summary["baseline_status"] is None and summary["primary_metric"] is None

    detail = run_detail(run)
    nodes = {n["node_id"]: n for n in detail["nodes"]}
    assert set(nodes) == {"A", "B", "C", "D"}
    assert nodes["A"]["depth"] == 0 or nodes["B"]["depth"] == 0  # cycle A<->B breaks somewhere
    assert nodes["B"]["alive"] is False and nodes["C"]["status"] is None and nodes["C"]["ledger"] == "not a dict"
    assert nodes["D"]["parent_node_id"] is None
    assert [w["work_id"] for w in nodes["A"]["work"]] == ["w1", "w3"]
    assert nodes["A"]["report_count"] == 0
    assert detail["baseline"] == {"state": None, "manifest": None}
    assert detail["selection"] is None and detail["resources"] == 5
    assert detail["journal_count"] == 2

    node = node_detail(run, "A")
    assert node is not None
    kinds = [h["kind"] for h in node["history"]]
    assert kinds.count("journal") == 2 and kinds.count("work") == 2
    assert node["history"][0]["details"] == {}  # non-dict details become {}


def test_find_run_rejects_traversal(tmp_path: Path) -> None:
    assert find_run(tmp_path, "../..") is None
    assert find_run(tmp_path, "missing") is None
    assert scan_overview(tmp_path) == {**scan_overview(tmp_path), "exists": False, "runs": [], "contracts": []}


def test_find_run_file_path_checks(target: Path) -> None:
    run = find_run(target, fx.RESEARCH_RUN)
    assert find_run_file(run, "discovery-notes.md") == (run / "discovery-notes.md").resolve()
    assert find_run_file(run, "logs/workers/N1/N1-w-001/result.md").is_file()
    assert find_run_file(run, "missing.md") is not None  # caller distinguishes 404
    assert find_run_file(run, "../../active-run.json") is None
    assert find_run_file(run, "logs/../../../active-run.json") is None
    assert find_run_file(run, "/etc/passwd") is None
    assert find_run_file(run, "") is None
    assert find_run_file(run, "baseline/baseline.json") is not None
    assert find_run_file(run, "nodes/N2/workspace/model.bin") is None  # not a text suffix


# --- server ------------------------------------------------------------------


@pytest.fixture(scope="module")
def server(target: Path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(target, target / "no-dist"))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _status(url: str) -> int:
    try:
        with urlopen(url) as resp:
            return resp.status
    except HTTPError as exc:
        return exc.code


def test_server_routes(server: str) -> None:
    overview = json.load(urlopen(f"{server}/api/overview"))
    assert len(overview["runs"]) == 6
    assert json.load(urlopen(f"{server}/api/runs/{fx.RESEARCH_RUN}"))["node_count"] == 5
    node = json.load(urlopen(f"{server}/api/runs/{fx.RESEARCH_RUN}/nodes/N2"))
    assert node["node_id"] == "N2" and len(node["reports"]) == 2
    for bad in (f"/api/runs/{fx.RESEARCH_RUN}/nodes/nope", f"/api/runs/{fx.RESEARCH_RUN}/other/N2", "/api/runs/nope", "/api/nope"):
        assert _status(f"{server}{bad}") == 404, bad
    assert _status(f"{server}/") == 503  # frontend not built


def test_server_files_route(server: str) -> None:
    with urlopen(f"{server}/api/runs/{fx.RESEARCH_RUN}/files/logs/workers/N2/N2-w-001/result.md") as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/plain")
        assert resp.read().decode().startswith("# N2: Snapshot ensemble on N1")
    with urlopen(f"{server}/api/runs/{fx.IDEATION_RUN}/files/ideas/snapshot-ensemble.md") as resp:
        assert resp.read().decode().startswith("# Snapshot ensemble")
    assert _status(f"{server}/api/runs/{fx.RESEARCH_RUN}/files/missing.md") == 404
    assert _status(f"{server}/api/runs/{fx.RESEARCH_RUN}/files/") == 404
    # traversal, percent-encoded so the client does not normalise it away
    assert _status(f"{server}/api/runs/{fx.RESEARCH_RUN}/files/%2e%2e/%2e%2e/active-run.json") == 403
    assert _status(f"{server}/api/runs/{fx.RESEARCH_RUN}/files/logs/%2e%2e/%2e%2e/%2e%2e/active-run.json") == 403
    assert _status(f"{server}/api/runs/{fx.RESEARCH_RUN}/files/nodes/N2/workspace/model.bin") == 403


def _post(url: str, body, *, raw: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    data = raw if raw is not None else json.dumps(body).encode()
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req) as resp:
            return resp.status, json.load(resp)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def test_server_post_message(server: str, target: Path) -> None:
    url = f"{server}/api/runs/{fx.RESEARCH_RUN}/messages"
    box = target / ".ai-scientist" / "runs" / fx.RESEARCH_RUN / "message-box"
    before = json.load(urlopen(f"{server}/api/runs/{fx.RESEARCH_RUN}/nodes/N4"))
    assert before["messages"] == [] and before["pending_messages"] == 0

    status, record = _post(url, {"node_id": "N4", "kind": "revision", "prompt": "use TTA with 8 crops"})
    assert status == 201
    assert record["node_id"] == "N4" and record["kind"] == "revision" and record["status"] == "pending"
    assert record["run_id"] == fx.RESEARCH_RUN and record["prompt"] == "use TTA with 8 crops"
    assert (box / f"{record['id']}.json").is_file()
    assert json.loads((box / f"{record['id']}.json").read_text()) == record

    after = json.load(urlopen(f"{server}/api/runs/{fx.RESEARCH_RUN}/nodes/N4"))
    assert [m["id"] for m in after["messages"]] == [record["id"]]
    assert after["pending_messages"] == 1
    assert after["history"][-1]["kind"] == "journal" and after["history"][-1]["details"]["message_id"] == record["id"]
    run = json.load(urlopen(f"{server}/api/runs/{fx.RESEARCH_RUN}"))
    assert run["messages"][0]["id"] == record["id"]  # newest first
    assert run["pending_messages"] == 2


def test_server_post_message_rejections(server: str) -> None:
    url = f"{server}/api/runs/{fx.RESEARCH_RUN}/messages"
    status, err = _post(url, {"node_id": "N2", "kind": "foo", "prompt": "x"})
    assert status == 400 and "kind" in err["error"]
    status, err = _post(url, {"node_id": "N9", "kind": "branch", "prompt": "x"})
    assert status == 400 and "unknown node" in err["error"]
    status, err = _post(url, {"node_id": "N2", "kind": "branch", "prompt": ""})
    assert status == 400 and "prompt" in err["error"]
    status, err = _post(url, None, raw=b"not json")
    assert status == 400 and "JSON object" in err["error"]
    status, err = _post(url, ["node_id"])
    assert status == 400 and "JSON object" in err["error"]

    status, err = _post(f"{server}/api/runs/nope/messages", {"node_id": "N2", "kind": "branch", "prompt": "x"})
    assert status == 404 and "unknown run" in err["error"]
    status, _ = _post(f"{server}/api/runs/{fx.RESEARCH_RUN}/nodes/N2", {"node_id": "N2", "kind": "branch", "prompt": "x"})
    assert status == 404
    status, _ = _post(f"{server}/api/overview", {})
    assert status == 404

    big = {"node_id": "N2", "kind": "branch", "prompt": "x" * 70_000}
    status, err = _post(url, big)
    assert status == 413 and "larger than" in err["error"]

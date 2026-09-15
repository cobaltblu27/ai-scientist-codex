"""Dashboard sessions (docs/SCHEMA.md 3.12): SessionManager with a fake backend, plus the /api/sessions routes."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dashboard.scan import scan_overview, session_detail, find_session
from dashboard.server import make_handler
from dashboard.sessions import LIVE_STATUSES, LaunchSpec, SessionError, SessionManager, build_launch_prompt, session_dir
from test_support import read_json, write_json

CONTRACT = "cifar10-accuracy"
IDEATION_RUN = "20260910-ideation-cifar10"
IDEAS = [("mixup-cutout-schedule", "Mixup and cutout"), ("snapshot-ensemble", "Snapshot ensemble"), ("stochastic-depth", "Stochastic depth")]
RECORD_KEYS = {
    "id", "backend", "status", "created_at", "updated_at", "run_id", "contract_path", "idea_batch", "prompt", "cwd",
    "owner_pid", "claude_session_id", "num_turns", "total_cost_usd", "error",
}


# --- fake backend ------------------------------------------------------------


class FakeClient:
    """Scripted client: init, one assistant line, then waits for a follow-up query before finishing the turn."""

    def __init__(self, *, fail_after_init: bool = False):
        self.fail_after_init = fail_after_init
        self.queries: list[str] = []
        self.interrupts = 0
        self.entered = threading.Event()
        self.exited = threading.Event()
        self._inbox: asyncio.Queue[str] | None = None

    async def __aenter__(self) -> "FakeClient":
        self._inbox = asyncio.Queue()
        self.entered.set()
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        self.exited.set()
        return False

    async def query(self, prompt: str) -> None:
        assert self._inbox is not None
        self.queries.append(prompt)
        await self._inbox.put(prompt)

    async def receive_messages(self):
        assert self._inbox is not None
        await self._inbox.get()  # the launch prompt
        yield {"type": "system", "subtype": "init", "session_id": "fake-session-1"}
        if self.fail_after_init:
            raise RuntimeError("cli died")
        yield {"type": "assistant", "text": "starting the campaign"}
        follow_up = await self._inbox.get()  # a dashboard message mid-turn
        yield {"type": "assistant", "text": f"noted: {follow_up}", "tool": "Skill"}
        yield {"type": "result", "subtype": "success", "session_id": "fake-session-1", "num_turns": 3, "total_cost_usd": 0.25, "is_error": False, "text": "done"}
        await asyncio.Event().wait()  # idle until cancelled

    async def interrupt(self) -> None:
        self.interrupts += 1


class FakeBackend:
    name = "fake"

    def __init__(self, *, unavailable: str | None = None, fail_after_init: bool = False):
        self.unavailable = unavailable
        self.fail_after_init = fail_after_init
        self.specs: list[LaunchSpec] = []
        self.clients: list[FakeClient] = []

    def unavailable_reason(self) -> str | None:
        return self.unavailable

    def open(self, spec: LaunchSpec) -> FakeClient:
        self.specs.append(spec)
        client = FakeClient(fail_after_init=self.fail_after_init)
        self.clients.append(client)
        return client

    def to_event(self, message: Any) -> dict[str, Any] | None:
        return message if isinstance(message, dict) else None


# --- helpers -----------------------------------------------------------------


def _target(tmp_path: Path) -> Path:
    root = tmp_path / ".ai-scientist"
    write_json(root / "contracts" / CONTRACT / "research-contract.json", {"research_contract": {"contract_id": CONTRACT, "goal": "beat the baseline"}})
    (root / "contracts" / "broken").mkdir(parents=True)
    (root / "contracts" / "broken" / "research-contract.json").write_text('{"research_contract": "nope"')
    run = root / "runs" / IDEATION_RUN
    (run / "run.md").parent.mkdir(parents=True)
    (run / "run.md").write_text("- status: complete\n")
    write_json(run / "contract.json", {"goal": "beat the baseline"})
    write_json(
        run / "ideas.json",
        {"run_id": IDEATION_RUN, "ideas": [{"id": i, "title": t, "idea_file": f"ideas/{i}.md", "pilot_report": f"logs/pilots/{i}/report.md"} for i, t in IDEAS]},
    )
    return tmp_path


def _events(target: Path, session_id: str) -> list[dict]:
    path = session_dir(target, session_id) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _wait(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def _record(target: Path, session_id: str) -> dict:
    return read_json(session_dir(target, session_id) / "session.json")


@pytest.fixture
def target(tmp_path: Path) -> Path:
    return _target(tmp_path)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def manager(target: Path, backend: FakeBackend):
    mgr = SessionManager(target, backend)
    yield mgr
    mgr.stop_all()


# --- launch ------------------------------------------------------------------


def test_launch_writes_record_and_idea_batch(target: Path, backend: FakeBackend, manager: SessionManager) -> None:
    record = manager.launch(CONTRACT, ["snapshot-ensemble", "mixup-cutout-schedule"], "use the conda env `ml`", run_id="run-a")
    assert set(record) == RECORD_KEYS
    assert record["status"] == "starting" and record["backend"] == "fake"
    assert record["run_id"] == "run-a" and record["owner_pid"] == os.getpid()
    assert record["contract_path"] == f".ai-scientist/contracts/{CONTRACT}/research-contract.json"
    assert record["idea_batch"] == f".ai-scientist/sessions/{record['id']}/ideas.json"
    assert record["created_at"].endswith("Z") and record["updated_at"].endswith("Z")
    assert record["claude_session_id"] and len(record["claude_session_id"]) == 36
    assert read_json(session_dir(target, record["id"]) / "session.json") == {**record, "updated_at": _record(target, record["id"])["updated_at"]}

    batch = read_json(target / record["idea_batch"])
    assert [i["id"] for i in batch["ideas"]] == ["snapshot-ensemble", "mixup-cutout-schedule"]  # selection order kept
    assert batch["ideas"][0]["idea_file"] == f".ai-scientist/runs/{IDEATION_RUN}/ideas/snapshot-ensemble.md"
    assert batch["ideas"][0]["pilot_report"] == f".ai-scientist/runs/{IDEATION_RUN}/logs/pilots/snapshot-ensemble/report.md"
    assert batch["ideas"][0]["source_run_id"] == IDEATION_RUN

    spec = backend.specs[0]
    assert spec.run_id == "run-a" and spec.cwd == target.resolve() and spec.claude_session_id == record["claude_session_id"]
    prompt = build_launch_prompt(spec)
    assert prompt.startswith("/goal ") and "ai-scientist:research-loop" in prompt
    assert "Run id: run-a." in prompt and record["idea_batch"] in prompt and "snapshot-ensemble, mixup-cutout-schedule" in prompt
    assert prompt.endswith("use the conda env `ml`")

    _wait(lambda: _record(target, record["id"])["status"] == "running")
    assert _record(target, record["id"])["claude_session_id"] == "fake-session-1"  # the backend's id wins once seen
    events = _events(target, record["id"])
    assert events[0]["type"] == "user" and events[0]["origin"] == "launch" and events[0]["text"] == prompt
    assert events[1]["subtype"] == "init"
    assert all(e["ts"].endswith("Z") for e in events)


def test_launch_default_run_id(target: Path, manager: SessionManager) -> None:
    record = manager.launch(CONTRACT, ["snapshot-ensemble"], "")
    assert record["run_id"].endswith(f"-research-{CONTRACT}")
    assert len(record["run_id"].split("-")[0]) == 8


def test_launch_rejections(target: Path, backend: FakeBackend, manager: SessionManager) -> None:
    with pytest.raises(SessionError) as err:
        manager.launch("nope", ["snapshot-ensemble"], "")
    assert err.value.status == 400 and "contract" in str(err.value)
    with pytest.raises(SessionError, match="invalid contract"):
        manager.launch("broken", ["snapshot-ensemble"], "")
    with pytest.raises(SessionError, match="idea_ids"):
        manager.launch(CONTRACT, [], "")
    with pytest.raises(SessionError, match="unknown idea ids: ghost"):
        manager.launch(CONTRACT, ["snapshot-ensemble", "ghost"], "")
    with pytest.raises(SessionError, match="longer than"):
        manager.launch(CONTRACT, ["snapshot-ensemble"], "x" * 20_001)
    with pytest.raises(SessionError, match="invalid run id"):
        manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="../x")

    (target / ".ai-scientist" / "runs" / "taken").mkdir()
    with pytest.raises(SessionError) as err:
        manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="taken")
    assert err.value.status == 409

    first = manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="run-b")
    with pytest.raises(SessionError) as err:
        manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="run-b")
    assert err.value.status == 409 and first["id"] in str(err.value)
    assert not (target / ".ai-scientist" / "sessions").is_dir() or len(list((target / ".ai-scientist" / "sessions").iterdir())) == 1


def test_launch_unavailable_backend(target: Path) -> None:
    manager = SessionManager(target, FakeBackend(unavailable="install it"))
    with pytest.raises(SessionError) as err:
        manager.launch(CONTRACT, ["snapshot-ensemble"], "")
    assert err.value.status == 503 and str(err.value) == "install it"


# --- steering ----------------------------------------------------------------


def test_send_mid_turn_interrupt_and_result(target: Path, backend: FakeBackend, manager: SessionManager) -> None:
    record = manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="run-c")
    sid = record["id"]
    _wait(lambda: len(_events(target, sid)) >= 3)  # launch, init, first assistant line: the turn is in flight

    event = manager.send(sid, "  try TTA  ")
    assert event["type"] == "user" and event["origin"] == "dashboard" and event["text"] == "try TTA"
    client = backend.clients[0]
    assert client.queries[-1] == "try TTA"  # delivered immediately, no Python-side queue
    _wait(lambda: _record(target, sid)["status"] == "idle")
    rec = _record(target, sid)
    assert rec["num_turns"] == 3 and rec["total_cost_usd"] == 0.25 and rec["error"] is None
    types = [(e["type"], e.get("subtype")) for e in _events(target, sid)]
    assert types[-3:] == [("user", None), ("assistant", None), ("result", "success")]

    manager.interrupt(sid)
    _wait(lambda: client.interrupts == 1)
    assert _events(target, sid)[-1] == {**_events(target, sid)[-1], "type": "dashboard", "subtype": "interrupt"}

    with pytest.raises(SessionError, match="text is required"):
        manager.send(sid, "   ")
    with pytest.raises(SessionError, match="longer than"):
        manager.send(sid, "x" * 20_001)

    manager.stop(sid)
    assert _record(target, sid)["status"] == "stopped"
    assert client.exited.is_set()
    assert not manager.get(sid)._thread.is_alive()
    with pytest.raises(SessionError) as err:
        manager.send(sid, "again")
    assert err.value.status == 409
    manager.stop(sid)  # idempotent
    manager.stop_all()
    assert _record(target, sid)["status"] == "stopped"


def test_backend_failure_marks_failed(target: Path) -> None:
    backend = FakeBackend(fail_after_init=True)
    manager = SessionManager(target, backend)
    record = manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="run-d")
    _wait(lambda: _record(target, record["id"])["status"] == "failed")
    rec = _record(target, record["id"])
    assert rec["error"] == "RuntimeError: cli died"
    assert _events(target, record["id"])[-1] == {**_events(target, record["id"])[-1], "type": "dashboard", "subtype": "failed", "text": "RuntimeError: cli died"}
    assert not manager.get(record["id"]).alive
    with pytest.raises(SessionError) as err:
        manager.send(record["id"], "hi")
    assert err.value.status == 409


def test_unknown_session(manager: SessionManager) -> None:
    for action in (lambda: manager.send("nope", "x"), lambda: manager.interrupt("nope"), lambda: manager.stop("nope")):
        with pytest.raises(SessionError) as err:
            action()
        assert err.value.status == 404


# --- records, reconcile, scanner -------------------------------------------


def test_reconcile_marks_orphans_detached(target: Path, backend: FakeBackend) -> None:
    root = target / ".ai-scientist"
    dead = {"id": "ses-dead", "backend": "claude", "status": "running", "created_at": "2026-09-14T10:00:00Z", "updated_at": "2026-09-14T10:00:00Z", "run_id": "run-x", "owner_pid": 2_000_000_000}
    alive = {"id": "ses-alive", "backend": "claude", "status": "idle", "created_at": "2026-09-14T11:00:00Z", "updated_at": "2026-09-14T11:00:00Z", "run_id": "run-y", "owner_pid": os.getppid()}
    done = {"id": "ses-done", "backend": "claude", "status": "stopped", "created_at": "2026-09-14T09:00:00Z", "updated_at": "2026-09-14T09:30:00Z", "run_id": "run-z", "owner_pid": 2_000_000_000}
    for rec in (dead, alive, done):
        write_json(root / "sessions" / rec["id"] / "session.json", rec)
    (root / "sessions" / "junk").mkdir()
    (root / "sessions" / "junk" / "session.json").write_text("{")

    manager = SessionManager(target, backend)
    records = {r["id"]: r for r in manager.records()}
    assert records["ses-dead"]["status"] == "detached" and records["ses-dead"]["updated_at"] != dead["updated_at"]
    assert records["ses-alive"]["status"] == "idle"
    assert records["ses-done"]["status"] == "stopped"
    assert [r["id"] for r in manager.records()] == ["ses-alive", "ses-dead", "ses-done"]  # newest first
    assert _events(target, "ses-dead")[-1]["subtype"] == "detached"

    # a record owned by this very process but unknown to the (new) manager is an orphan too
    mine = {**dead, "id": "ses-mine", "owner_pid": os.getpid()}
    write_json(root / "sessions" / "ses-mine" / "session.json", mine)
    fresh = SessionManager(target, backend)  # reconciles on construction
    assert {r["id"]: r["status"] for r in fresh.records()}["ses-mine"] == "detached"
    assert fresh.reconcile() == []  # nothing left to fix
    with pytest.raises(SessionError) as err:
        manager.send("ses-dead", "x")
    assert err.value.status == 409 and "not owned" in str(err.value)


def test_scanner_exposes_sessions_and_ideas(target: Path, backend: FakeBackend, manager: SessionManager) -> None:
    record = manager.launch(CONTRACT, ["snapshot-ensemble"], "", run_id="run-e")
    _wait(lambda: len(_events(target, record["id"])) >= 3)
    overview = scan_overview(target)
    assert [s["id"] for s in overview["sessions"]] == [record["id"]]
    assert overview["ideas"] == [
        {
            "run_id": IDEATION_RUN,
            "goal": "beat the baseline",
            "ideas": [{"id": i, "title": t, "idea_file": f"ideas/{i}.md", "pilot_report": f"logs/pilots/{i}/report.md"} for i, t in IDEAS],
        }
    ]
    assert overview["runs"][0]["run_id"] == IDEATION_RUN and overview["runs"][0]["session"] is None

    detail = session_detail(find_session(target, record["id"]))
    assert detail["id"] == record["id"] and detail["event_count"] == len(detail["events"]) >= 3
    assert detail["events"][1]["subtype"] == "init"
    assert find_session(target, "../x") is None and find_session(target, "missing") is None

    # once the orchestrator creates the run, the run summary links back to its session
    write_json(target / ".ai-scientist" / "runs" / "run-e" / "loop-state.json", {"run_id": "run-e", "phase": "research", "phase_status": "running", "active": True, "updated_at": "2026-09-15T00:00:00Z", "state": {}})
    runs = {r["run_id"]: r for r in scan_overview(target)["runs"]}
    assert runs["run-e"]["session"]["id"] == record["id"] and runs["run-e"]["session"]["status"] in LIVE_STATUSES


# --- HTTP routes -------------------------------------------------------------


def _post(url: str, body: Any) -> tuple[int, Any]:
    req = Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:
            return resp.status, json.load(resp)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def _get(url: str) -> tuple[int, Any]:
    try:
        with urlopen(url) as resp:
            return resp.status, json.load(resp)
    except HTTPError as exc:
        return exc.code, json.load(exc)


@pytest.fixture
def server(target: Path, backend: FakeBackend):
    manager = SessionManager(target, backend)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(target, target / "no-dist", manager))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        manager.stop_all()


def test_server_session_routes(server: str, target: Path, backend: FakeBackend) -> None:
    assert _get(f"{server}/api/sessions") == (200, [])
    status, err = _post(f"{server}/api/sessions", {"contract_id": CONTRACT, "idea_ids": [], "prompt": ""})
    assert status == 400 and "idea_ids" in err["error"]
    status, err = _post(f"{server}/api/sessions", {"contract_id": "broken", "idea_ids": ["snapshot-ensemble"], "prompt": ""})
    assert status == 400 and "contract" in err["error"]
    status, err = _post(f"{server}/api/sessions", {"contract_id": CONTRACT, "idea_ids": "snapshot-ensemble", "prompt": ""})
    assert status == 400

    status, record = _post(f"{server}/api/sessions", {"contract_id": CONTRACT, "idea_ids": ["snapshot-ensemble"], "prompt": "go", "run_id": "run-h"})
    assert status == 201 and set(record) == RECORD_KEYS and record["run_id"] == "run-h"
    sid = record["id"]
    status, err = _post(f"{server}/api/sessions", {"contract_id": CONTRACT, "idea_ids": ["snapshot-ensemble"], "prompt": "", "run_id": "run-h"})
    assert status == 409

    _wait(lambda: len(_events(target, sid)) >= 3)
    status, event = _post(f"{server}/api/sessions/{sid}/messages", {"text": "look at N1"})
    assert status == 202 and event["type"] == "user" and event["origin"] == "dashboard" and event["text"] == "look at N1"
    _wait(lambda: _get(f"{server}/api/sessions/{sid}")[1]["status"] == "idle")
    status, detail = _get(f"{server}/api/sessions/{sid}")
    assert status == 200 and detail["num_turns"] == 3 and detail["events"][-1]["type"] == "result"
    status, listing = _get(f"{server}/api/sessions")
    assert status == 200 and [s["id"] for s in listing] == [sid]
    status, overview = _get(f"{server}/api/overview")
    assert overview["sessions"][0]["id"] == sid and overview["ideas"][0]["run_id"] == IDEATION_RUN

    status, rec = _post(f"{server}/api/sessions/{sid}/interrupt", {})
    assert status == 200 and rec["id"] == sid
    _wait(lambda: backend.clients[0].interrupts == 1)

    status, rec = _post(f"{server}/api/sessions/{sid}/stop", {})
    assert status == 200 and rec["status"] == "stopped"
    status, err = _post(f"{server}/api/sessions/{sid}/messages", {"text": "again"})
    assert status == 409

    assert _post(f"{server}/api/sessions/nope/messages", {"text": "x"})[0] == 404
    assert _post(f"{server}/api/sessions/nope/stop", {})[0] == 404
    assert _post(f"{server}/api/sessions/{sid}/other", {})[0] == 404
    assert _get(f"{server}/api/sessions/nope")[0] == 404


def test_server_session_unavailable(target: Path) -> None:
    manager = SessionManager(target, FakeBackend(unavailable="claude-agent-sdk is not installed"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(target, target / "no-dist", manager))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, err = _post(f"http://127.0.0.1:{httpd.server_port}/api/sessions", {"contract_id": CONTRACT, "idea_ids": ["snapshot-ensemble"], "prompt": ""})
        assert status == 503 and "not installed" in err["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()

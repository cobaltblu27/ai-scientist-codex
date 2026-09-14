"""Message box (docs/SCHEMA.md 3.11): core.message_box round trip and the `message-box` CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.main import main as cli_main
from core.message_box import KINDS, STATUSES, MessageBoxError, add, list_messages, load, message_box_dir, update
from test_support import read_json, write_json

RUN_ID = "run-mb"


def _minimal_run(target: Path) -> Path:
    run = target / ".ai-scientist" / "runs" / RUN_ID
    write_json(
        run / "loop-state.json",
        {
            "run_id": RUN_ID,
            "phase": "research",
            "state": {"nodes": {"N1": {"status": "completed"}, "N2": {"status": "running"}}, "work": {}},
        },
    )
    write_json(target / ".ai-scientist" / "active-run.json", {"schema_version": 1, "run_id": RUN_ID, "phase": "research", "status": "active"})
    return run


def _journal(run: Path) -> list[dict]:
    path = run / "journal.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def target(tmp_path: Path) -> Path:
    _minimal_run(tmp_path)
    return tmp_path


def test_constants_match_schema() -> None:
    assert KINDS == {"revision", "branch"}
    assert STATUSES == ("pending", "acknowledged", "completed", "rejected", "cancelled")


def test_add_round_trip(target: Path) -> None:
    record = add(target, RUN_ID, "N2", "branch", "  try RandAugment  ")
    path = message_box_dir(target, RUN_ID) / f"{record['id']}.json"
    assert path.is_file()
    assert record["id"] == path.stem
    assert read_json(path) == record
    assert record["prompt"] == "try RandAugment"  # stripped
    assert record["status"] == "pending" and record["run_id"] == RUN_ID and record["node_id"] == "N2"
    assert record["created_at"] == record["updated_at"]
    assert (record["work_id"], record["result_node_id"], record["note"]) == (None, None, None)
    assert load(target, RUN_ID, record["id"]) == record

    journal = _journal(target / ".ai-scientist" / "runs" / RUN_ID)
    assert len(journal) == 1
    rec = journal[0]
    assert rec["event_type"] == "message" and rec["node_id"] == "N2" and rec["run_id"] == RUN_ID
    assert rec["details"]["message_id"] == record["id"]
    assert rec["details"]["status"] == "pending" and rec["details"]["kind"] == "branch"


def test_add_validation(target: Path) -> None:
    with pytest.raises(MessageBoxError, match="kind"):
        add(target, RUN_ID, "N1", "foo", "x")
    with pytest.raises(MessageBoxError, match="unknown node"):
        add(target, RUN_ID, "N9", "revision", "x")
    with pytest.raises(MessageBoxError, match="prompt is required"):
        add(target, RUN_ID, "N1", "revision", "   ")
    with pytest.raises(MessageBoxError, match="node_id is required"):
        add(target, RUN_ID, "", "revision", "x")
    with pytest.raises(MessageBoxError, match="unknown run"):
        add(target, "nope", "N1", "revision", "x")
    assert list_messages(target, RUN_ID) == []
    assert _journal(target / ".ai-scientist" / "runs" / RUN_ID) == []


def test_list_filters_by_status_and_node(target: Path) -> None:
    a = add(target, RUN_ID, "N1", "revision", "first")
    b = add(target, RUN_ID, "N2", "branch", "second")
    c = add(target, RUN_ID, "N2", "revision", "third")
    update(target, RUN_ID, c["id"], "rejected", note="no")

    # Sorted by (created_at, id); three adds inside one second only fix the set, not the order.
    listed = list_messages(target, RUN_ID)
    assert {m["prompt"] for m in listed} == {"first", "second", "third"}
    assert [(m["created_at"], m["id"]) for m in listed] == sorted((m["created_at"], m["id"]) for m in listed)
    assert {m["id"] for m in list_messages(target, RUN_ID, status="pending")} == {a["id"], b["id"]}
    assert {m["id"] for m in list_messages(target, RUN_ID, node_id="N2")} == {b["id"], c["id"]}
    assert [m["id"] for m in list_messages(target, RUN_ID, status="pending", node_id="N2")] == [b["id"]]
    assert list_messages(target, RUN_ID, status="completed") == []

    # malformed and foreign files are skipped, not raised
    box = message_box_dir(target, RUN_ID)
    (box / "broken.json").write_text('{"id": "broken"')
    (box / "no-id.json").write_text('{"status": "pending"}')
    (box / "notes.txt").write_text("ignored")
    assert len(list_messages(target, RUN_ID)) == 3
    assert list_messages(target, "missing-run") == []


def test_update_transitions(target: Path) -> None:
    run = target / ".ai-scientist" / "runs" / RUN_ID
    msg = add(target, RUN_ID, "N1", "revision", "warmup")

    with pytest.raises(MessageBoxError, match="work-id"):
        update(target, RUN_ID, msg["id"], "acknowledged")
    acked = update(target, RUN_ID, msg["id"], "acknowledged", work_id="N1-r-002")
    assert acked["status"] == "acknowledged" and acked["work_id"] == "N1-r-002"
    assert load(target, RUN_ID, msg["id"])["status"] == "acknowledged"

    done = update(target, RUN_ID, msg["id"], "completed", result_node_id="N3")
    assert done["status"] == "completed" and done["result_node_id"] == "N3" and done["work_id"] == "N1-r-002"

    # terminal: nothing else allowed
    for status in ("pending", "acknowledged", "rejected", "cancelled"):
        with pytest.raises(MessageBoxError, match="cannot move"):
            update(target, RUN_ID, msg["id"], status, work_id="w", note="n")

    events = _journal(run)
    assert [e["details"]["status"] for e in events] == ["pending", "acknowledged", "completed"]
    assert all(e["event_type"] == "message" and e["node_id"] == "N1" for e in events)
    assert events[1]["details"]["work_id"] == "N1-r-002" and events[2]["details"]["result_node_id"] == "N3"


def test_update_rejected_requires_note(target: Path) -> None:
    msg = add(target, RUN_ID, "N2", "branch", "x")
    with pytest.raises(MessageBoxError, match="note"):
        update(target, RUN_ID, msg["id"], "rejected")
    rejected = update(target, RUN_ID, msg["id"], "rejected", note="out of budget")
    assert rejected["status"] == "rejected" and rejected["note"] == "out of budget"
    with pytest.raises(MessageBoxError, match="cannot move"):
        update(target, RUN_ID, msg["id"], "acknowledged", work_id="w")


def test_update_invalid_inputs(target: Path) -> None:
    msg = add(target, RUN_ID, "N2", "branch", "x")
    with pytest.raises(MessageBoxError, match="status must be"):
        update(target, RUN_ID, msg["id"], "done")
    with pytest.raises(MessageBoxError, match="cannot move"):
        update(target, RUN_ID, msg["id"], "pending")
    with pytest.raises(MessageBoxError, match="unknown message"):
        update(target, RUN_ID, "msg-missing", "cancelled")
    with pytest.raises(MessageBoxError, match="invalid message id"):
        update(target, RUN_ID, "../escape", "cancelled")
    cancelled = update(target, RUN_ID, msg["id"], "cancelled")
    assert cancelled["status"] == "cancelled"


def test_add_without_ledger_skips_node_check(tmp_path: Path) -> None:
    run = tmp_path / ".ai-scientist" / "runs" / "bare"
    run.mkdir(parents=True)
    record = add(tmp_path, "bare", "anything", "revision", "x")
    assert record["node_id"] == "anything"


# --- CLI ---------------------------------------------------------------------


def _cli(capsys: pytest.CaptureFixture[str], target: Path, *args: str) -> tuple[int, dict]:
    code = cli_main(["--target-repo", str(target), "message-box", *args])
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_cli_add_list_update(capsys: pytest.CaptureFixture[str], target: Path) -> None:
    code, added = _cli(capsys, target, "add", "--run-id", RUN_ID, "--node-id", "N2", "--kind", "branch", "--prompt", "cli branch")
    assert code == 0 and added["status"] == "ok"
    message = added["message"]
    assert message["status"] == "pending" and message["node_id"] == "N2" and message["kind"] == "branch"
    assert (message_box_dir(target, RUN_ID) / f"{message['id']}.json").is_file()

    # --prompt-file and active-run fallback for --run-id
    prompt_file = target / "prompt.md"
    prompt_file.write_text("from a file\n")
    code, added2 = _cli(capsys, target, "add", "--node-id", "N1", "--kind", "revision", "--prompt-file", str(prompt_file))
    assert code == 0 and added2["message"]["prompt"] == "from a file" and added2["message"]["run_id"] == RUN_ID

    code, listed = _cli(capsys, target, "list", "--run-id", RUN_ID)
    assert code == 0 and listed["status"] == "ok" and listed["run_id"] == RUN_ID
    assert listed["count"] == 2 and {m["id"] for m in listed["messages"]} == {message["id"], added2["message"]["id"]}
    code, pending_n2 = _cli(capsys, target, "list", "--run-id", RUN_ID, "--status", "pending", "--node-id", "N2")
    assert pending_n2["count"] == 1 and pending_n2["messages"][0]["id"] == message["id"]

    code, updated = _cli(capsys, target, "update", "--run-id", RUN_ID, "--id", message["id"], "--status", "acknowledged", "--work-id", "N2-b-001")
    assert code == 0 and updated["message"]["status"] == "acknowledged" and updated["message"]["work_id"] == "N2-b-001"

    code, err = _cli(capsys, target, "update", "--run-id", RUN_ID, "--id", message["id"], "--status", "rejected")
    assert code == 1 and err["status"] == "error" and "note" in err["error"]

    code, err = _cli(capsys, target, "add", "--run-id", RUN_ID, "--node-id", "N9", "--kind", "revision", "--prompt", "x")
    assert code == 1 and err["status"] == "error" and "unknown node" in err["error"]

    code, err = _cli(capsys, target, "add", "--run-id", "missing", "--node-id", "N1", "--kind", "revision", "--prompt", "x")
    assert code == 1 and "unknown run" in err["error"]

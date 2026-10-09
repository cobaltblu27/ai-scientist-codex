"""`ai-scientist validate loop-state` against runs written the way docs/SCHEMA.md describes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cli.main import main as cli_main
from test_support import write_json
from validation.run import validate_loop_state_run

TS = "2026-09-09T18:14:29Z"


def journal_line(**fields: Any) -> str:
    record = {"event_type": "state_transition", "timestamp": TS, "run_id": "run-1", "details": {"command": "research-loop-checkpoint"}}
    record.update(fields)
    return json.dumps(record)


def minimal_state(**overrides: Any) -> dict[str, Any]:
    state = {
        "schema_version": 1,
        "run_id": "run-1",
        "active": True,
        "phase": "research",
        "phase_status": "running",
        "updated_at": TS,
        "last_transition_id": "tr-1",
        "run_outcome": None,
        "blocked_reason": None,
        "links": {"config": "config.md", "learning_notes": "learning-notes.md"},
        "state": {
            "orchestrator": {"next_action": "dispatch N1"},
            "baseline": {"status": "not_required"},
            "nodes": {"N1": {"status": "running", "updated_at": TS, "parent_node_id": None}},
            "work": {"N1-w-001": {"status": "running", "agent_thread_id": "worker-1", "result_ref": "logs/workers/N1/N1-w-001/result.md", "node": "N1"}},
            "tasks": {},
            "resources": {},
            "resource_queue": {"pending": [], "released": [], "completed": []},
            "selection": {"status": "pending", "selected_node": None},
        },
    }
    state.update(overrides)
    return state


def write_run(tmp_path: Path, state: dict[str, Any] | None = None, journal: list[str] | None = None) -> tuple[Path, Path]:
    root = tmp_path / ".ai-scientist"
    run = root / "runs" / "run-1"
    write_json(run / "loop-state.json", state if state is not None else minimal_state())
    lines = journal if journal is not None else [journal_line(event_type="setup", details={"command": "bootstrap"}), journal_line(transition_id="tr-1")]
    run.mkdir(parents=True, exist_ok=True)
    (run / "journal.jsonl").write_text("\n".join(lines) + "\n")
    return root, run


def test_minimal_schema_run_has_no_problems(tmp_path: Path) -> None:
    root, run = write_run(tmp_path)
    assert validate_loop_state_run(root, run) == []


def test_cli_reports_ok_and_exit_zero(tmp_path: Path, capsys) -> None:
    write_run(tmp_path)
    assert cli_main(["--target-repo", str(tmp_path), "validate", "loop-state", "--run-id", "run-1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["problems"] == []
    assert payload["run_id"] == "run-1"


def test_cli_reports_problems_and_nonzero_exit(tmp_path: Path, capsys) -> None:
    state = minimal_state()
    del state["updated_at"]
    state["state"]["work"]["N1-w-001"].pop("agent_thread_id")
    write_run(tmp_path, state)
    assert cli_main(["--target-repo", str(tmp_path), "validate", "loop-state", "--run-id", "run-1"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    joined = "\n".join(payload["problems"])
    assert "$ missing required key updated_at" in joined
    assert "$.state.work.N1-w-001 missing required key agent_thread_id" in joined


def test_missing_loop_state_is_a_problem(tmp_path: Path) -> None:
    root = tmp_path / ".ai-scientist"
    run = root / "runs" / "run-1"
    run.mkdir(parents=True)
    problems = validate_loop_state_run(root, run)
    assert len(problems) == 1 and "loop-state.json: missing" in problems[0]


def test_phase_and_status_enums(tmp_path: Path) -> None:
    root, run = write_run(tmp_path, minimal_state(phase="ideation", phase_status="blocked_on_user"))
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "$.phase must be one of research, review, writeup" in joined
    assert "$.phase_status must be one of" in joined


def test_active_must_agree_with_terminal_status(tmp_path: Path) -> None:
    root, run = write_run(tmp_path, minimal_state(phase_status="success", active=True))
    assert any("$.active must be false" in p for p in validate_loop_state_run(root, run))
    root, run = write_run(tmp_path, minimal_state(phase_status="running", active=False))
    assert any("$.active must be true" in p for p in validate_loop_state_run(root, run))


def test_blocked_requires_reason(tmp_path: Path) -> None:
    root, run = write_run(tmp_path, minimal_state(phase_status="blocked", active=False))
    assert any("blocked_reason is required" in p for p in validate_loop_state_run(root, run))
    root, run = write_run(tmp_path, minimal_state(phase_status="blocked", active=False, blocked_reason="dataset unavailable"))
    assert validate_loop_state_run(root, run) == []


def test_last_transition_id_must_exist_in_journal(tmp_path: Path) -> None:
    root, run = write_run(tmp_path, minimal_state(last_transition_id="tr-unknown"))
    assert any("tr-unknown" in p and "no matching journal.jsonl record" in p for p in validate_loop_state_run(root, run))


def test_last_transition_id_may_live_in_details(tmp_path: Path) -> None:
    lines = [json.dumps({"event_type": "state_transition", "timestamp": TS, "run_id": "run-1", "transition_id": "tr-1", "details": {"transition_id": "tr-1"}})]
    root, run = write_run(tmp_path, journal=lines)
    assert validate_loop_state_run(root, run) == []


def test_unset_last_transition_id_is_tolerated(tmp_path: Path) -> None:
    root, run = write_run(tmp_path, minimal_state(last_transition_id=None), journal=[journal_line(event_type="setup")])
    assert validate_loop_state_run(root, run) == []


def test_journal_lines_must_parse_and_carry_required_keys(tmp_path: Path) -> None:
    lines = [
        journal_line(transition_id="tr-1"),
        "{not json",
        json.dumps({"event_type": "note", "timestamp": TS}),
        json.dumps({"event_type": "made_up", "timestamp": TS, "run_id": "run-1", "details": {}}),
        json.dumps({"event_type": "state_transition", "timestamp": TS, "run_id": "run-1", "details": {}}),
    ]
    root, run = write_run(tmp_path, journal=lines)
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "line 2 is not valid JSON" in joined
    assert "record 2: $ missing required key run_id" in joined
    assert "record 2: $ missing required key details" in joined
    assert "record 3: $.event_type must be one of" in joined
    assert "record 4: state_transition records require transition_id" in joined


def test_missing_journal_is_a_problem(tmp_path: Path) -> None:
    root, run = write_run(tmp_path)
    (run / "journal.jsonl").unlink()
    assert any(p.startswith("journal.jsonl: missing") for p in validate_loop_state_run(root, run))


def test_work_entries_require_the_four_keys_and_a_known_node(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["work"] = {
        "bad": {"status": "running"},
        "rank-1": {"status": "completed", "agent_thread_id": "ranker", "result_ref": "logs/rankings/rank-1/result.md", "node": None},
        "orphan": {"status": "running", "agent_thread_id": "w", "result_ref": "x.md", "node": "N9"},
    }
    root, run = write_run(tmp_path, state)
    joined = "\n".join(validate_loop_state_run(root, run))
    for key in ("agent_thread_id", "result_ref", "node"):
        assert f"$.state.work.bad missing required key {key}" in joined
    assert "$.state.work.rank-1" not in joined
    assert "$.state.work.orphan.node 'N9' is not a node" in joined


def test_nodes_require_status_and_updated_at(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N2"] = {"parent_node_id": "N1"}
    root, run = write_run(tmp_path, state)
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "$.state.nodes.N2 missing required key status" in joined
    assert "$.state.nodes.N2 missing required key updated_at" in joined


def test_selection_file_must_match_state(tmp_path: Path) -> None:
    state = minimal_state(phase_status="success", active=False, run_outcome="success")
    state["state"]["nodes"]["N1"]["status"] = "accepted"
    state["state"]["work"]["N1-w-001"]["status"] = "completed"
    state["state"]["selection"] = {"status": "final", "selected_node": "N1"}
    root, run = write_run(tmp_path, state)
    write_json(run / "selection.json", {"run_id": "run-1", "status": "final", "selected_node": "N2"})
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "selection.json: $ missing required key acceptance_rationale" in joined
    assert "differs from loop-state selection" in joined
    write_json(run / "selection.json", {"run_id": "run-1", "status": "final", "selected_node": "N1", "acceptance_rationale": "beats threshold"})
    assert validate_loop_state_run(root, run) == []


def test_active_run_for_this_run_is_checked(tmp_path: Path) -> None:
    root, run = write_run(tmp_path)
    write_json(root / "active-run.json", {"schema_version": 1, "run_id": "run-1", "phase": "research", "status": "active", "updated_at": TS, "target_repo": str(tmp_path)})
    assert any("active-run.json: $ missing required key target_repository" in p for p in validate_loop_state_run(root, run))


def test_extra_keys_everywhere_are_tolerated(tmp_path: Path) -> None:
    state = minimal_state(custom_top_level={"anything": 1})
    state["state"]["extra_section"] = [1, 2, 3]
    state["state"]["nodes"]["N1"]["metrics"] = {"score": 0.1, "n_seeds": 1, "fidelity": "full", "train_loss": 0.4}
    state["state"]["work"]["N1-w-001"]["ranking_id"] = "rank-1"
    root, run = write_run(tmp_path, state, journal=[journal_line(transition_id="tr-1", subagent_id="x", custom="y")])
    assert validate_loop_state_run(root, run) == []


def scored_node(metrics: dict[str, Any] | None = None, prediction: dict[str, Any] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"status": "completed", "updated_at": TS, "parent_node_id": None}
    node["metrics"] = metrics if metrics is not None else {"rmse": 2.31, "n_seeds": 3, "seed_std": 0.02, "fidelity": "full", "cost_gpu_hours": 1.5}
    if prediction is not None:
        node["prediction"] = prediction
    return node


def write_config(run: Path, primary_metric: str = "rmse") -> None:
    (run / "config.md").write_text(f"---\nrun_id: run-1\nprimary_metric: {primary_metric}\n---\n")


def test_node_metrics_and_prediction_are_accepted(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N1"] = scored_node(prediction={"gain": 0.05, "confidence": "low"})
    root, run = write_run(tmp_path, state)
    write_config(run)
    assert validate_loop_state_run(root, run) == []


def test_node_metrics_require_seeds_and_fidelity(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N1"] = scored_node({"rmse": 2.31})
    root, run = write_run(tmp_path, state)
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "$.state.nodes.N1.metrics missing required key n_seeds" in joined
    assert "$.state.nodes.N1.metrics missing required key fidelity" in joined


def test_node_metrics_require_std_for_several_seeds(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N1"] = scored_node({"rmse": 2.31, "n_seeds": 3, "fidelity": "full"})
    root, run = write_run(tmp_path, state)
    assert any("seed_std is required when n_seeds >= 2" in p for p in validate_loop_state_run(root, run))
    state["state"]["nodes"]["N1"] = scored_node({"rmse": 2.31, "n_seeds": 1, "seed_std": None, "fidelity": "screen"})
    root, run = write_run(tmp_path, state)
    assert validate_loop_state_run(root, run) == []


def test_node_metrics_must_carry_the_configured_primary_metric(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N1"] = scored_node({"auroc": 0.8, "n_seeds": 1, "fidelity": "full"})
    root, run = write_run(tmp_path, state)
    assert validate_loop_state_run(root, run) == []
    write_config(run)
    assert any("missing primary metric 'rmse'" in p for p in validate_loop_state_run(root, run))
    state["state"]["nodes"]["N1"] = scored_node({"rmse": "2.31", "n_seeds": 1, "fidelity": "full"})
    root, run = write_run(tmp_path, state)
    assert any("metrics.rmse must be a number" in p for p in validate_loop_state_run(root, run))


def test_node_metrics_reject_bad_values(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N1"] = scored_node({"rmse": 2.31, "n_seeds": 0, "seed_std": -1, "fidelity": "Full", "cost_gpu_hours": -2})
    root, run = write_run(tmp_path, state)
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "n_seeds must be an integer >= 1" in joined
    assert "seed_std must be a number >= 0 or null" in joined
    assert "fidelity must be a lowercase token" in joined
    assert "cost_gpu_hours must be a number >= 0" in joined


def test_node_prediction_requires_gain_and_known_confidence(tmp_path: Path) -> None:
    state = minimal_state()
    state["state"]["nodes"]["N1"]["prediction"] = {"gain": "big", "confidence": "certain"}
    root, run = write_run(tmp_path, state)
    joined = "\n".join(validate_loop_state_run(root, run))
    assert "prediction.gain must be a number" in joined
    assert "prediction.confidence must be one of low, medium, high" in joined
    state["state"]["nodes"]["N1"]["prediction"] = {"confidence": "low"}
    root, run = write_run(tmp_path, state)
    assert any("$.state.nodes.N1.prediction missing required key gain" in p for p in validate_loop_state_run(root, run))

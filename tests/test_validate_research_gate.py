"""research_to_review and review_to_writeup gates over a docs/SCHEMA.md research run."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from test_support import write_json
from validation.run import ValidationError, check_config, check_research_to_review, check_review_to_writeup, main as validate_main

TS = "2026-09-09T18:14:29Z"
CONFIG_MD = """---
run_id: run-1
target_repository: {target}
contract_path: contract.json
idea_batch: .ai-scientist/runs/ideation-1/ideas.json
primary_metric: accuracy
primary_metric_direction: higher_is_better
success_threshold: 0.9
active_node_cap: 4
ranking_top_n: 3
python_env: uv run python
---

# Run run-1

Restates the frozen contract.
"""


def accepted_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": "run-1",
        "active": False,
        "phase": "research",
        "phase_status": "success",
        "updated_at": TS,
        "last_transition_id": "tr-final",
        "run_outcome": "success",
        "blocked_reason": None,
        "links": {"config": "config.md"},
        "state": {
            "orchestrator": {"next_action": "hand off to review", "completion_audit": "all criteria met"},
            "baseline": {"status": "ready", "result_ref": "logs/baseline/b-1/result.md"},
            "nodes": {
                "N1": {"status": "accepted", "updated_at": TS, "parent_node_id": None, "result_ref": "logs/workers/N1/N1-w-001/result.md"},
                "N2": {"status": "rejected", "updated_at": TS, "parent_node_id": "N1"},
            },
            "work": {
                "N1-w-001": {"status": "completed", "agent_thread_id": "worker-1", "result_ref": "logs/workers/N1/N1-w-001/result.md", "node": "N1"},
                "rank-1": {"status": "completed", "agent_thread_id": "ranker", "result_ref": "logs/rankings/rank-1/result.md", "node": None},
            },
            "tasks": {},
            "resources": {"leases": {}},
            "resource_queue": {"pending": [], "released": [], "completed": ["N1-w-001"]},
            "selection": {"status": "final", "selected_node": "N1"},
        },
    }


def write_research_run(tmp_path: Path, state: dict[str, Any] | None = None, *, contract: Any = None, config_md: str | None = None) -> tuple[Path, Path]:
    root = tmp_path / ".ai-scientist"
    run = root / "runs" / "run-1"
    run.mkdir(parents=True, exist_ok=True)
    (run / "config.md").write_text(config_md if config_md is not None else CONFIG_MD.format(target=tmp_path))
    write_json(tmp_path / "contract.json", contract if contract is not None else {"research_contract": {"contract_id": "c1", "goal": "beat baseline"}})
    write_json(run / "loop-state.json", state if state is not None else accepted_state())
    journal = [
        {"event_type": "setup", "timestamp": TS, "run_id": "run-1", "details": {"command": "bootstrap"}},
        {"event_type": "state_transition", "timestamp": TS, "run_id": "run-1", "transition_id": "tr-final", "details": {"command": "research-loop-checkpoint"}},
    ]
    (run / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in journal) + "\n")
    return root, run


def test_accepted_run_passes_research_to_review(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path)
    check_research_to_review(root, run)
    assert validate_main([str(tmp_path), "--gate", "research_to_review", "--run-id", "run-1"]) == 0


def test_selection_json_is_checked_when_present(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path)
    write_json(run / "selection.json", {"run_id": "run-1", "status": "final", "selected_node": "N1", "acceptance_rationale": "0.93 > 0.9"})
    check_research_to_review(root, run)
    write_json(run / "selection.json", {"run_id": "run-1", "status": "pending", "selected_node": "N1", "acceptance_rationale": "x"})
    with pytest.raises(ValidationError):
        check_research_to_review(root, run)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda s: s.__setitem__("phase_status", "running") or s.__setitem__("active", True), "not complete"),
        (lambda s: s["state"]["selection"].__setitem__("status", "pending"), "selection must be final"),
        (lambda s: s["state"]["selection"].__setitem__("selected_node", "N9"), "not a node"),
        (lambda s: s["state"]["nodes"]["N1"].__setitem__("status", "candidate"), "must be accepted"),
        (lambda s: s["state"]["work"]["N1-w-001"].__setitem__("status", "running"), "unresolved work item"),
        (lambda s: s["state"]["tasks"].__setitem__("t1", {"status": "running"}), "unresolved tasks item"),
        (lambda s: s["state"]["resources"].__setitem__("leases", {"lease-1": {"status": "acquired"}}), "active resource leases"),
        (lambda s: s["state"]["resource_queue"].__setitem__("pending", [{"work_id": "N3-w-001"}]), "resource queue blocks"),
        (lambda s: s["state"]["resource_queue"].__setitem__("released", ["N3-w-001"]), "resource queue blocks"),
        (lambda s: s["state"]["work"]["N1-w-001"].pop("result_ref"), "missing required key result_ref"),
        (lambda s: s.__setitem__("phase_status", "exhausted"), "not complete"),
    ],
)
def test_research_to_review_failures(tmp_path: Path, mutate, fragment: str) -> None:
    state = accepted_state()
    mutate(state)
    root, run = write_research_run(tmp_path, state)
    with pytest.raises(ValidationError, match=fragment):
        check_research_to_review(root, run)


def test_config_md_requires_frontmatter_keys(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path, config_md="---\nrun_id: run-1\ncontract_path: contract.json\n---\n")
    with pytest.raises(ValidationError, match="missing fields: idea_batch, primary_metric, success_threshold"):
        check_config(root, run)


def test_config_md_contract_path_resolves_against_target_repo(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path)
    cfg = check_config(root, run)
    assert cfg["research_contract"] == {"contract_id": "c1", "goal": "beat baseline"}
    assert cfg["resolved_contract_path"] == str(tmp_path / "contract.json")
    (tmp_path / "contract.json").unlink()
    with pytest.raises(ValidationError, match="contract_path does not exist"):
        check_config(root, run)


def test_config_md_accepts_bare_and_absolute_contract(tmp_path: Path) -> None:
    absolute = tmp_path / "elsewhere" / "c.json"
    write_json(absolute, {"goal": "bare form"})
    config_md = CONFIG_MD.format(target=tmp_path).replace("contract_path: contract.json", f"contract_path: {absolute}")
    root, run = write_research_run(tmp_path, config_md=config_md)
    assert check_config(root, run)["research_contract"] == {"goal": "bare form"}


def test_config_md_rejects_non_json_contract(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path)
    (tmp_path / "contract.json").write_text("not json")
    with pytest.raises(ValidationError, match="invalid JSON"):
        check_config(root, run)


def test_missing_config_md_fails_closed(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path)
    (run / "config.md").unlink()
    with pytest.raises(ValidationError, match="missing required config.md"):
        check_research_to_review(root, run)


def review(decision: str) -> dict[str, Any]:
    return {
        "verdict": {"decision": decision, "summary": "..."},
        "leakage": {"pass": True, "summary": "no leakage"},
        "split_integrity": {"pass": True, "summary": "fixed split"},
        "baseline_comparison": {"pass": True, "summary": "beats baseline"},
    }


def test_review_to_writeup_decisions(tmp_path: Path) -> None:
    root, run = write_research_run(tmp_path)
    for decision in ("accept", "revise"):
        write_json(run / "review" / "structured-review.json", review(decision))
        check_review_to_writeup(root, run)
    write_json(run / "review" / "structured-review.json", review("reject"))
    with pytest.raises(ValidationError, match="reject review blocks"):
        check_review_to_writeup(root, run)
    write_json(run / "review" / "structured-review.json", review("maybe"))
    with pytest.raises(ValidationError, match="verdict.decision"):
        check_review_to_writeup(root, run)
    broken = review("accept")
    del broken["leakage"]
    write_json(run / "review" / "structured-review.json", broken)
    with pytest.raises(ValidationError, match="missing leakage"):
        check_review_to_writeup(root, run)

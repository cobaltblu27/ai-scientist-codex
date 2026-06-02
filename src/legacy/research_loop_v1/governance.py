from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ResearchConfig
from .journal import append_jsonl, utc_now, write_json


def _preserve_or_write(path: Path, data: Any) -> None:
    if not path.exists():
        write_json(path, data)


def load_idea(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "ideas" in data and isinstance(data["ideas"], list) and data["ideas"]:
        return data["ideas"][0]
    if isinstance(data, dict):
        return data
    raise ValueError("--idea-json must contain an idea object or {ideas:[...]}")


def bootstrap(config: ResearchConfig) -> dict[str, Any]:
    config.target_repo.mkdir(parents=True, exist_ok=True)
    fresh = not config.ai_root.exists()
    if fresh and config.idea_json is None:
        raise SystemExit("ERROR: fresh target requires --idea-json")
    config.ai_root.mkdir(parents=True, exist_ok=True)
    idea: dict[str, Any]
    ideas_path = config.ai_root / "ideas" / "ideas.json"
    if ideas_path.exists():
        ideas = json.loads(ideas_path.read_text())
        idea = ideas.get("ideas", [ideas])[0]
    else:
        if config.idea_json is None:
            raise SystemExit("ERROR: existing target without ideas requires --idea-json for this run")
        idea = load_idea(config.idea_json)
        write_json(ideas_path, {"ideas": [idea], "created_at": utc_now(), "source": str(config.idea_json)})
    _preserve_or_write(config.ai_root / "config.json", {
        "schema_version": "ai-scientist-config-v1",
        "target_repo": str(config.target_repo),
        "strictness_mode": config.strictness_mode,
        "metric_key": config.metric_key,
        "metric_direction": config.metric_direction,
        "api_budgets": {"codex": "unlimited" if config.agent_runner == "codex" else 0},
        "run_root_policy": "run-owned authoritative artifacts under .ai-scientist/runs/<run-id>",
    })
    if config.run_dir.exists():
        raise SystemExit(f"ERROR: run already exists, refusing to overwrite: {config.run_dir}")
    config.run_dir.mkdir(parents=True)
    write_json(config.run_dir / "dependency-plan.json", {"planned_dependencies": [{"name": "stdlib", "status": "not_needed", "reason": "research orchestrator uses Python standard library only"}]})
    write_json(config.run_dir / "dependency-status.json", {"status": "approved", "dependencies": [{"name": "stdlib", "status": "not_needed"}]})
    append_jsonl(
        config.run_dir / "api-ledger.jsonl",
        {
            "timestamp": utc_now(),
            "phase": "research",
            "provider": "codex" if config.agent_runner == "codex" else "fixture",
            "budget_key": "codex-research-loop",
            "cached": False,
            "event": "runner-selected",
            "external_calls": config.agent_runner == "codex",
        },
    )
    guidelines = config.target_repo / "GUIDELINES.md"
    write_json(
        config.run_dir / "principles.json",
        {
            "principles": [
                {
                    "id": "target-guidance",
                    "name": "target guidance",
                    "principle": "Preserve target-root guidance, dataset split integrity, and auditable research evidence.",
                    "description": guidelines.read_text(errors="replace")[:1000] if guidelines.exists() else "No target-root GUIDELINES.md present.",
                    "gates": ["research_to_review"],
                    "evidence_artifacts": ["research-plan.json", "selection.json", "nodes/<node-id>/split_integrity.json", "nodes/<node-id>/leakage_check.json"],
                }
            ]
        },
    )
    write_json(config.run_dir / "run-status.json", {"run_id": config.run_id, "phase": "research", "status": "running", "strictness_mode": config.strictness_mode, "last_validation": None, "last_validations": {}})
    write_json(config.run_dir / "research-plan.json", {
        "run_id": config.run_id,
        "idea": idea,
        "strictness_mode": config.strictness_mode,
        "entry_script": config.entry_script,
        "dataset_loader": config.dataset_loader,
        "baseline_command": config.baseline_command,
        "metric_key": config.metric_key,
        "metric_direction": config.metric_direction,
        "success_threshold": config.success_threshold,
        "split_policy": config.split_policy,
        "split_manifest": str(config.split_manifest) if config.split_manifest else None,
        "resource_caps": {
            "max_gpus": config.resources.max_gpus,
            "cpu_cores": config.resources.cpu_cores,
            "memory_mb": config.resources.memory_mb,
            "max_parallel": config.max_parallel,
        },
        "agent_runner": config.agent_runner,
        "created_at": utc_now(),
    })
    return idea


def update_status(run_dir: Path, **fields: Any) -> None:
    path = run_dir / "run-status.json"
    status = json.loads(path.read_text())
    status.update(fields)
    write_json(path, status)

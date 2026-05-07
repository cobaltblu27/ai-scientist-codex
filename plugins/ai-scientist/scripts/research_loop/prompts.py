from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import ACTIONS, STRICTNESS_MODES, ResearchConfig
from .journal import write_json

TEMPLATE_VERSION = "research-loop-prompts-v1"

TEMPLATES = {
    "draft": "Draft a manifest-only experiment implementation for the idea.",
    "debug": "Debug the failed manifest-only experiment without direct repository writes.",
    "improve": "Improve the prior manifest-only experiment while preserving split integrity.",
    "tuning": "Tune safe hyperparameters and report metric impact through manifests only.",
    "ablation": "Create a manifest-only ablation to isolate the claimed effect.",
}


def root_guidance(target_repo: Path) -> dict[str, Any]:
    path = target_repo / "GUIDELINES.md"
    if not path.exists():
        return {"present": False, "summary": "No target-root GUIDELINES.md was present."}
    text = path.read_text(errors="replace")
    return {"present": True, "summary": text[:2000]}


def build_prompt(config: ResearchConfig, action: str, node_id: str, parent_node_id: str | None, idea: dict[str, Any]) -> dict[str, Any]:
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    if config.strictness_mode not in STRICTNESS_MODES:
        raise ValueError(f"unknown strictness mode: {config.strictness_mode}")
    resources = getattr(config, "resources", None)
    metadata = {
        "schema_version": "agent-manifest-v1",
        "template_id": action,
        "template_version": TEMPLATE_VERSION,
        "action": action,
        "strictness_mode": config.strictness_mode,
        "node_id": node_id,
        "parent_node_id": parent_node_id,
        "idea": idea,
        "metric_contract": {"metric_key": config.metric_key, "metric_direction": config.metric_direction, "success_threshold": config.success_threshold},
        "split_policy": config.split_policy,
        "root_guidance": root_guidance(config.target_repo),
        "expected_manifest_schema_version": "agent-manifest-v1",
        "required_deliverables": ["metrics.json", "split_integrity.json", "leakage_check.json", "result_summary.json", "mode_deliverables.json"],
        "manifest_only": True,
        "metadata": {
            "mode": config.strictness_mode,
            "action": action,
            "metric_key": config.metric_key,
            "metric_direction": config.metric_direction,
            "resource_caps": {
                "max_gpus": getattr(resources, "max_gpus", None),
                "cpu_cores": getattr(resources, "cpu_cores", None),
                "memory_mb": getattr(resources, "memory_mb", None),
            },
        },
        "instructions": (
            f"{TEMPLATES[action]} Return one JSON manifest only. Do not write directly to the target repo. "
            "All generated file paths must be relative to the node workspace."
        ),
    }
    return metadata


def write_prompt(path: Path, prompt: dict[str, Any]) -> None:
    write_json(path, prompt)

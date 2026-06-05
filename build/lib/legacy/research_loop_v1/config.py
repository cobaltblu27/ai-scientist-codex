from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STRICTNESS_MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
ACTIONS = {"draft", "debug", "improve", "tuning", "ablation"}
METRIC_DIRECTIONS = {"maximize", "minimize"}


def slugify(value: str, fallback: str = "research") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return (slug or fallback)[:80]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


@dataclass(frozen=True)
class ResourceCaps:
    max_gpus: int | None = None
    cpu_cores: int | None = None
    memory_mb: int | None = None


@dataclass(frozen=True)
class ResearchConfig:
    target_repo: Path
    idea_json: Path | None
    run_id: str
    strictness_mode: str
    entry_script: str | None
    dataset_loader: str | None
    baseline_command: str
    metric_key: str
    metric_direction: str
    success_threshold: float | None
    split_policy: str
    split_manifest: Path | None
    max_nodes: int
    max_debug_attempts: int
    max_improve_attempts: int
    max_tuning_attempts: int
    max_ablation_attempts: int
    max_parallel: int
    resources: ResourceCaps
    node_timeout_sec: int
    agent_runner: str
    codex_cmd: str
    codex_model: str | None
    fixture_scenario: str

    @property
    def ai_root(self) -> Path:
        return self.target_repo / ".ai-scientist"

    @property
    def run_dir(self) -> Path:
        return self.ai_root / "runs" / self.run_id


def _cap(value: str | None, unlimited_words: set[str]) -> int | None:
    if value is None or value.lower() in unlimited_words:
        return None
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("resource caps must be non-negative or unlimited")
    return parsed


def parse_args(argv: list[str] | None = None) -> ResearchConfig:
    parser = argparse.ArgumentParser(description="Run a Codex-native AI Scientist research loop")
    parser.add_argument("--target-repo", type=Path, required=True)
    parser.add_argument("--idea-json", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--strictness-mode", choices=sorted(STRICTNESS_MODES), default="balanced")
    parser.add_argument("--entry-script")
    parser.add_argument("--dataset-loader")
    parser.add_argument("--baseline-command", required=True)
    parser.add_argument("--metric-key", required=True)
    parser.add_argument("--metric-direction", choices=sorted(METRIC_DIRECTIONS), required=True)
    parser.add_argument("--success-threshold", type=float)
    parser.add_argument("--split-policy", default="declared split policy")
    parser.add_argument("--split-manifest", type=Path)
    parser.add_argument("--max-nodes", type=int, default=1)
    parser.add_argument("--max-debug-attempts", type=int, default=1)
    parser.add_argument("--max-improve-attempts", type=int, default=1)
    parser.add_argument("--max-tuning-attempts", type=int, default=1)
    parser.add_argument("--max-ablation-attempts", type=int, default=1)
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--max-gpus", default="all")
    parser.add_argument("--cpu-cores", default="all")
    parser.add_argument("--memory-mb", default="unlimited")
    parser.add_argument("--node-timeout-sec", type=int, default=600)
    parser.add_argument("--agent-runner", choices=["codex", "fixture"], default="fixture")
    parser.add_argument("--codex-cmd", default="codex")
    parser.add_argument("--codex-model")
    parser.add_argument("--fixture-scenario", default="success", choices=["success", "no_improvement", "runtime_mutation", "unsafe_manifest", "minimize_success"])
    ns = parser.parse_args(argv)
    if ns.max_nodes < 1 or ns.max_parallel < 1:
        parser.error("--max-nodes and --max-parallel must be positive")
    if ns.node_timeout_sec < 1:
        parser.error("--node-timeout-sec must be positive")
    target = ns.target_repo.resolve()
    run_id = slugify(ns.run_id or f"research-{ns.strictness_mode}")
    return ResearchConfig(
        target_repo=target,
        idea_json=ns.idea_json.resolve() if ns.idea_json else None,
        run_id=run_id,
        strictness_mode=ns.strictness_mode,
        entry_script=ns.entry_script,
        dataset_loader=ns.dataset_loader,
        baseline_command=ns.baseline_command,
        metric_key=ns.metric_key,
        metric_direction=ns.metric_direction,
        success_threshold=ns.success_threshold,
        split_policy=ns.split_policy,
        split_manifest=ns.split_manifest.resolve() if ns.split_manifest else None,
        max_nodes=ns.max_nodes,
        max_debug_attempts=ns.max_debug_attempts,
        max_improve_attempts=ns.max_improve_attempts,
        max_tuning_attempts=ns.max_tuning_attempts,
        max_ablation_attempts=ns.max_ablation_attempts,
        max_parallel=ns.max_parallel,
        resources=ResourceCaps(_cap(ns.max_gpus, {"all", "unlimited"}), _cap(ns.cpu_cores, {"all", "unlimited"}), _cap(ns.memory_mb, {"all", "unlimited"})),
        node_timeout_sec=ns.node_timeout_sec,
        agent_runner=ns.agent_runner,
        codex_cmd=ns.codex_cmd,
        codex_model=ns.codex_model,
        fixture_scenario=ns.fixture_scenario,
    )

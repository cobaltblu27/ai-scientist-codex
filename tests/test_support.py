from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
PLUGIN_ROOT = REPO_ROOT
AI_SCIENTIST_CMD = ["uv", "run", "--project", str(REPO_ROOT), "ai-scientist"]
VALIDATE_RUN_ARGS = [*AI_SCIENTIST_CMD, "validate", "run"]

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def run_python(args: list[str | Path], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*map(str, args)],
        cwd=cwd or REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_minimal_research_run(target: Path, *, direction: str = "maximize") -> Path:
    """Minimal accepted research run: the artifacts the writeup and validation gates actually read."""
    ai = target / ".ai-scientist"
    run = ai / "runs" / "run-001"
    node = run / "nodes" / "node-001"
    write_json(ai / "config.json", {"target_repo": str(target), "resources": {"max_parallel": 1}})
    metric_key = "accuracy" if direction == "maximize" else "loss"
    baseline_value = 0.50 if direction == "maximize" else 0.50
    candidate_value = 0.70 if direction == "maximize" else 0.30
    write_json(run / "baseline" / "metrics.json", {metric_key: baseline_value, "score": baseline_value})
    write_json(node / "node.json", {"node_id": "node-001", "action": "improve", "status": "completed"})
    write_json(node / "metrics.json", {metric_key: candidate_value, "score": candidate_value})
    write_json(run / "selection.json", {"selected_node": "node-001", "metric_key": metric_key, "metric_direction": direction, "baseline_metric": baseline_value, "selected_metric": candidate_value, "comparison": ">" if direction == "maximize" else "<", "threshold_passed": True})
    return run

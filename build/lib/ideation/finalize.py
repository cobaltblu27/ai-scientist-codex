#!/usr/bin/env python3
"""Retired hook-driven ideation finalizer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def finalize_ideation(target_repo: Path, state: dict[str, Any], plugin_root: Path | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "hook_driven_ideation_finalizer_retired",
        "message": "Use `ai-scientist ideation finalize-ready --json-file <final-ideas.json>` in the create_goal-driven ideation workflow.",
        "run_id": state.get("run_id"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    result = finalize_ideation(args.target_repo, {"run_id": args.run_id})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

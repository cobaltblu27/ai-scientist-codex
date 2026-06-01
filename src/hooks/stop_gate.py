#!/usr/bin/env python3
"""Codex Stop hook for AI Scientist continuation state."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.state import (
    StopDecision,
    evaluate_stop_decision,
    log_stop_decision,
    resolve_target_repo_from_payload,
)


def load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Codex hook payload must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, help="Override target repository for tests or wrapper launches.")
    args = parser.parse_args(argv)

    try:
        payload = load_payload()
        target_repo = args.target_repo.resolve() if args.target_repo else resolve_target_repo_from_payload(payload)
        decision = evaluate_stop_decision(target_repo, payload)
        log_stop_decision(target_repo, decision, payload)
        output = decision.to_hook_output()
    except Exception as exc:  # noqa: BLE001 - Stop hooks must fail closed.
        output = StopDecision(
            "block",
            "ai_scientist_stop_hook_error",
            f"AI Scientist Stop hook failed before normal continuation handling: {exc}. Continue once, inspect hook/state files, and repair before stopping.",
        ).to_hook_output()
        print(f"AI Scientist Stop hook error: {exc}", file=sys.stderr)

    sys.stdout.write(json.dumps(output, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

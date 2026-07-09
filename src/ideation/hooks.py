#!/usr/bin/env python3
"""Retired ideation hook entrypoint.

Ideation is now goal-driven through `create_goal`. This module remains only so
old hook invocations fail open instead of importing removed legacy helpers.
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", nargs="?")
    parser.parse_args(argv)
    if sys.stdin.isatty():
        payload = {}
    else:
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
    print(json.dumps({"decision": "allow", "message": "AI Scientist ideation hooks are retired; use create_goal-driven ideation.", "event": payload.get("hook_event_name")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

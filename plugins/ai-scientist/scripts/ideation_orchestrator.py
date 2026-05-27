#!/usr/bin/env python3
"""Retired entrypoint for the old Python-owned ideation orchestrator."""
from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write(
        "ERROR: ideation_orchestrator.py is retired. Use ai_scientist_state_cli.py "
        "ideation start/resume plus the current Codex session as the orchestrator.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

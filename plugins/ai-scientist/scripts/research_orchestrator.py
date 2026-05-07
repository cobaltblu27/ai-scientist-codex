#!/usr/bin/env python3
"""Thin CLI entrypoint for the Codex-native AI Scientist research loop."""
from __future__ import annotations

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from research_loop.orchestrator import main

if __name__ == "__main__":
    raise SystemExit(main())

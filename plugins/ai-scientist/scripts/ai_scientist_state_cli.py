#!/usr/bin/env python3
"""Compatibility wrapper for the unified AI Scientist CLI."""
from __future__ import annotations

from _ai_scientist_src import ensure_src

ensure_src()

from ai_scientist_codex.cli.main import *  # noqa: F401,F403
from ai_scientist_codex.cli.main import main


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compatibility wrapper for the AI Scientist Stop hook."""
from __future__ import annotations

from _ai_scientist_src import ensure_src

ensure_src()

from ai_scientist_codex.hooks.stop_gate import *  # noqa: F401,F403
from ai_scientist_codex.hooks.stop_gate import main


if __name__ == "__main__":
    raise SystemExit(main())

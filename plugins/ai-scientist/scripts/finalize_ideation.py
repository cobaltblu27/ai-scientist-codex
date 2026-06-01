#!/usr/bin/env python3
"""Compatibility wrapper for AI Scientist ideation finalization."""
from __future__ import annotations

from _ai_scientist_src import ensure_src

ensure_src()

from ai_scientist_codex.ideation.finalize import *  # noqa: F401,F403
from ai_scientist_codex.ideation.finalize import main


if __name__ == "__main__":
    raise SystemExit(main())

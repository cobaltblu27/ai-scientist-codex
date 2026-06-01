#!/usr/bin/env python3
"""Compatibility wrapper for AI Scientist usage-cap helpers."""
from __future__ import annotations

from _ai_scientist_src import ensure_src

ensure_src()

from ai_scientist_codex.research.usage_cap import *  # noqa: F401,F403

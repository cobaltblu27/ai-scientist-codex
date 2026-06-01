#!/usr/bin/env python3
"""Compatibility wrapper for AI Scientist ideation state helpers."""
from __future__ import annotations

import importlib
import sys

from _ai_scientist_src import ensure_src

_WRAPPER_NAME = __name__
ensure_src()

_module = importlib.import_module("ai_scientist_codex.ideation.state")
globals().update(_module.__dict__)
sys.modules[_WRAPPER_NAME] = _module

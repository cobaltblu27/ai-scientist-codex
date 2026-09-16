"""Where the CLI's bundled data lives: JSON schemas and the built dashboard frontend.

Both ship inside the Python packages (`validation/schemas/`, `dashboard/dist/`),
so the same lookup works from a source checkout (`PYTHONPATH=src`) and from an
installed wheel. The Vite sources next to `dashboard/` exist only in a checkout.
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

SCHEMA_NAMES = ("active-run", "journal", "loop-state", "message", "selection")


def schemas_dir() -> Path:
    return Path(str(files("validation").joinpath("schemas")))


def frontend_dist_dir() -> Path:
    return Path(str(files("dashboard").joinpath("dist")))


def frontend_source_dir() -> Path:
    """`src/frontend/` in a checkout; a nonexistent path in a wheel install."""
    return Path(str(files("dashboard"))).parent / "frontend"

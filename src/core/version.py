"""The CLI's own version: wheel metadata, else `pyproject.toml` of the checkout it runs from."""
from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DISTRIBUTION = "ai-scientist"


def cli_version() -> str:
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        return str(tomllib.loads(pyproject.read_text())["project"]["version"])
    except (OSError, ValueError, KeyError):
        return "0+unknown"

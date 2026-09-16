"""Read the YAML frontmatter of a Markdown file without a YAML dependency.

Frontmatter in this project (`config.md`, `run.md`) is a flat mapping of scalar
values. Nested structures are not supported; a line that does not look like
`key: value` is ignored so a hand-written file never makes the reader fail.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Return the flat key/value mapping between the leading `---` fences, or {}."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, Any] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, raw = line.partition(":")
        if not sep or not key.strip() or key[0].isspace():
            continue
        out[key.strip()] = _scalar(raw)
    return {}  # no closing fence: treat as no frontmatter


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Frontmatter of `path`, or {} when the file is missing or unreadable."""
    try:
        return parse_frontmatter(path.read_text())
    except OSError:
        return {}


def read_status_line(path: Path) -> str | None:
    """First `- status: <token>` bullet in a Markdown file such as an ideation `run.md`."""
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- status:"):
            value = stripped[len("- status:"):].strip().strip("`").strip()
            return value or None
    return None

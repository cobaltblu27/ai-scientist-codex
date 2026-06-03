from __future__ import annotations

from pathlib import Path


def plugin_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".codex-plugin" / "plugin.json").exists():
            return candidate
    return Path(__file__).resolve().parents[1]

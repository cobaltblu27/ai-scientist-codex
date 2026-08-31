from __future__ import annotations

import os
from pathlib import Path

PLUGIN_MARKERS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")


def plugin_root(start: Path | None = None) -> Path:
    """Locate the plugin checkout under either runtime.

    Both runtimes export a root when running as an installed plugin; otherwise
    walk up for whichever manifest is present.
    """
    for env_key in ("CLAUDE_PLUGIN_ROOT", "CODEX_PLUGIN_ROOT"):
        value = os.environ.get(env_key)
        if value and Path(value).is_dir():
            return Path(value).resolve()
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in PLUGIN_MARKERS):
            return candidate
    return Path(__file__).resolve().parents[1]

"""Locate the installed plugin checkout (skills, agents, manifests).

The CLI itself ships as a wheel and carries its own data (see `core.assets`);
the plugin directory is only needed where Claude Code has to load the skills,
such as the dashboard launching a session through the SDK. Resolution order:

1. `AI_SCIENTIST_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, `CODEX_PLUGIN_ROOT` (a dir holding a manifest)
2. a source checkout containing this file
3. the Claude Code install under `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/installed_plugins.json`
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PLUGIN_MARKERS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
PLUGIN_ENV_KEYS = ("AI_SCIENTIST_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CODEX_PLUGIN_ROOT")
INSTALLED_PLUGIN_KEY = "ai-scientist@ai-scientist"
INSTALL_HINT = (
    "ai-scientist plugin not found; run `claude plugin marketplace add cobaltblu27/ai-scientist-codex` and "
    "`claude plugin install ai-scientist@ai-scientist`, or set AI_SCIENTIST_PLUGIN_ROOT to a checkout"
)


class PluginNotFound(RuntimeError):
    pass


def is_plugin_dir(path: Path) -> bool:
    return any((path / marker).is_file() for marker in PLUGIN_MARKERS)


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def installed_plugin_dir(config_dir: Path | None = None) -> Path | None:
    """The `ai-scientist` install Claude Code recorded, if its directory still exists."""
    registry = (config_dir or claude_config_dir()) / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(registry.read_text())
    except (OSError, ValueError):
        return None
    entries = data.get("plugins", {}).get(INSTALLED_PLUGIN_KEY) if isinstance(data, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        path = entry.get("installPath") if isinstance(entry, dict) else None
        if isinstance(path, str) and is_plugin_dir(Path(path)):
            return Path(path).resolve()
    return None


def find_plugin_root(start: Path | None = None) -> tuple[Path, str] | None:
    """`(path, source)` with source `env`, `checkout`, or `installed`; None when nothing is found."""
    for key in PLUGIN_ENV_KEYS:
        value = os.environ.get(key)
        if value and is_plugin_dir(Path(value)):
            return Path(value).resolve(), "env"
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if is_plugin_dir(candidate):
            return candidate, "checkout"
    installed = installed_plugin_dir()
    if installed is not None:
        return installed, "installed"
    return None


def plugin_root(start: Path | None = None) -> Path:
    found = find_plugin_root(start)
    if found is None:
        raise PluginNotFound(INSTALL_HINT)
    return found[0]


def plugin_version(root: Path) -> str | None:
    """`version` from `.claude-plugin/plugin.json`, else from the Codex manifest."""
    for marker in PLUGIN_MARKERS:
        try:
            value = json.loads((root / marker).read_text()).get("version")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(value, str):
            return value
    return None

"""`ai-scientist doctor`: where this install finds its plugin, schemas, frontend, and SDK."""
from __future__ import annotations

import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from core.assets import SCHEMA_NAMES, frontend_dist_dir, frontend_source_dir, schemas_dir
from core.plugin import INSTALL_HINT, find_plugin_root, plugin_version
from core.version import cli_version


def _sdk_version() -> str | None:
    try:
        return version("claude-agent-sdk")
    except PackageNotFoundError:
        return None


def _claude_binary() -> str | None:
    """`bundled` when the SDK ships its own CLI (it prefers that), else the `claude` on PATH."""
    try:
        import claude_agent_sdk
    except ImportError:
        return shutil.which("claude")
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    return "bundled" if bundled.is_file() else shutil.which("claude")


def report(plugin_dir: Path | None = None) -> dict[str, Any]:
    from dashboard.frontend import dist_state

    problems: list[str] = []
    found = (plugin_dir.resolve(), "flag") if plugin_dir else find_plugin_root()
    plugin_root, plugin_source = found if found else (None, None)
    plugin_ver = plugin_version(plugin_root) if plugin_root else None
    if plugin_root is None:
        problems.append(INSTALL_HINT)
    cli = cli_version()
    skew = plugin_root is not None and plugin_ver != cli
    if skew:
        problems.append(f"plugin version {plugin_ver or 'unknown'} differs from CLI version {cli}; update the plugin or reinstall the CLI")

    schemas = {name: (schemas_dir() / f"{name}.schema.json").is_file() for name in SCHEMA_NAMES}
    missing = [name for name, ok in schemas.items() if not ok]
    if missing:
        problems.append(f"missing schema files: {', '.join(missing)}")

    sources, dist = frontend_source_dir(), frontend_dist_dir()
    state = dist_state(sources, dist)
    if state == "unavailable":
        problems.append("dashboard frontend is not built and this install has no sources; install the release wheel")
    elif state == "missing":
        problems.append("dashboard frontend is not built; run `ai-scientist dashboard --build-only`")

    sdk = _sdk_version()
    if sdk is None:
        problems.append("claude-agent-sdk is not installed; the dashboard cannot launch sessions (install the `dashboard` extra)")
    claude = _claude_binary()
    if claude is None:
        problems.append("no `claude` binary: the SDK does not bundle one and none is on PATH")

    return {
        "version": cli,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "plugin_dir": str(plugin_root) if plugin_root else None,
        "plugin_source": plugin_source,
        "plugin_version": plugin_ver,
        "version_skew": skew,
        "schemas_dir": str(schemas_dir()),
        "schemas": schemas,
        "frontend": {"dist_dir": str(dist), "state": state, "sources": str(sources) if (sources / "package.json").is_file() else None},
        "sdk": sdk,
        "claude": claude,
        "uv": shutil.which("uv"),
        "npm": shutil.which("npm"),
        "problems": problems,
    }

"""Install the plugin's committed Codex agent definitions."""
from __future__ import annotations

from pathlib import Path

from core.plugin import plugin_root

MANAGED_MARKER_PREFIX = "# ai-scientist agent: "
MANAGED_GLOB = "ai-scientist-*.toml"
IDEATION_ROLES = frozenset({"generator", "critic", "ranker"})
RESEARCH_ROLES = frozenset({"baseline-worker", "worker", "ranker", "revision-worker"})


class AgentInstallError(RuntimeError):
    pass


def ideation_agent_name(role: str) -> str:
    if role not in IDEATION_ROLES:
        raise AgentInstallError(f"invalid ideation agent role: {role}")
    return f"ai-scientist-ideation-{role}"


def research_agent_name(role: str) -> str:
    if role not in RESEARCH_ROLES:
        raise AgentInstallError(f"invalid research agent role: {role}")
    return f"ai-scientist-research-{role}"


def source_agents(root: Path | None = None) -> list[Path]:
    return sorted((root or plugin_root()).joinpath("agents").glob(MANAGED_GLOB))


def target_agents_dir(codex_home: Path | None = None, target_repo: Path | None = None) -> Path:
    if codex_home is not None and target_repo is not None:
        raise AgentInstallError("pass only one of --codex-home or --target-repo")
    if target_repo is not None:
        return target_repo.resolve() / ".codex" / "agents"
    return (codex_home or Path.home() / ".codex").expanduser().resolve() / "agents"


def is_managed_agent_file(path: Path) -> bool:
    if not path.exists():
        return False
    first = path.read_text().splitlines()[:1]
    return bool(first and first[0].strip().startswith(MANAGED_MARKER_PREFIX))


def install_agents(
    *,
    codex_home: Path | None = None,
    target_repo: Path | None = None,
    force: bool = False,
    root: Path | None = None,
) -> list[dict[str, str]]:
    sources = source_agents(root)
    if not sources:
        raise AgentInstallError("plugin has no committed agent definitions")

    agents_dir = target_agents_dir(codex_home, target_repo)
    agents_dir.mkdir(parents=True, exist_ok=True)
    current = {source.name for source in sources}
    for path in agents_dir.glob(MANAGED_GLOB):
        if path.name not in current and is_managed_agent_file(path):
            path.unlink()

    installed = []
    for source in sources:
        path = agents_dir / source.name
        if path.exists() and not force and not is_managed_agent_file(path):
            raise AgentInstallError(f"unmanaged agent file exists: {path}")
        path.write_text(source.read_text())
        installed.append({"name": source.stem, "path": str(path), "source": str(source)})
    return installed

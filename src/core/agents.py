"""Generated Codex native-agent registry for AI Scientist subagents."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.plugin import plugin_root

MANAGED_MARKER_PREFIX = "# ai-scientist agent: "
AGENT_DIR = "agents"
MANAGED_GLOB = "ai-scientist-*.toml"


class AgentInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    prompt_source: str
    model_reasoning_effort: str

    @property
    def marker(self) -> str:
        return f"{MANAGED_MARKER_PREFIX}{self.name}"

    @property
    def filename(self) -> str:
        return f"{self.name}.toml"


def _specs() -> list[AgentSpec]:
    """One agent per prompt file."""
    specs = [
        AgentSpec(
            name="ai-scientist-ideation-generator",
            description="AI Scientist ideation generator.",
            prompt_source="prompts/ideation/generator.md",
            model_reasoning_effort="xhigh",
        ),
        AgentSpec(
            name="ai-scientist-ideation-critic",
            description="AI Scientist ideation critic.",
            prompt_source="prompts/ideation/critic.md",
            model_reasoning_effort="xhigh",
        ),
        AgentSpec(
            name="ai-scientist-ideation-ranker",
            description="AI Scientist ideation candidate ranker.",
            prompt_source="prompts/ideation/ranker.md",
            model_reasoning_effort="xhigh",
        ),
        AgentSpec(
            name="ai-scientist-research-baseline-worker",
            description="AI Scientist research baseline and fixed-split worker.",
            prompt_source="prompts/research-loop/baseline-worker.md",
            model_reasoning_effort="medium",
        ),
        AgentSpec(
            name="ai-scientist-research-worker",
            description="AI Scientist research node worker.",
            prompt_source="prompts/research-loop/worker.md",
            model_reasoning_effort="xhigh",
        ),
        AgentSpec(
            name="ai-scientist-research-ranker",
            description="AI Scientist comparative research branch ranker.",
            prompt_source="prompts/research-loop/ranker.md",
            model_reasoning_effort="xhigh",
        ),
        AgentSpec(
            name="ai-scientist-research-revision-worker",
            description="AI Scientist research revision worker.",
            prompt_source="prompts/research-loop/revision-worker.md",
            model_reasoning_effort="xhigh",
        ),
    ]
    return sorted(specs, key=lambda spec: spec.name)


AGENT_SPECS: tuple[AgentSpec, ...] = tuple(_specs())


def agent_names() -> list[str]:
    return [spec.name for spec in AGENT_SPECS]


IDEATION_ROLES = frozenset({"generator", "critic", "ranker"})
RESEARCH_ROLES = frozenset({"baseline-worker", "worker", "ranker", "revision-worker"})


def ideation_agent_name(role: str) -> str:
    if role not in IDEATION_ROLES:
        raise AgentInstallError(f"invalid ideation agent role: {role}")
    return f"ai-scientist-ideation-{role}"


def research_agent_name(role: str) -> str:
    if role not in RESEARCH_ROLES:
        raise AgentInstallError(f"invalid research agent role: {role}")
    return f"ai-scientist-research-{role}"


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1 :]).lstrip("\n") + ("\n" if text.endswith("\n") else "")
    return text


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_agent_toml(spec: AgentSpec, *, root: Path | None = None) -> str:
    source_root = root or plugin_root()
    prompt_path = source_root / spec.prompt_source
    if not prompt_path.exists():
        raise AgentInstallError(f"missing agent prompt source for {spec.name}: {spec.prompt_source}")
    prompt = strip_frontmatter(prompt_path.read_text())
    if not prompt.strip():
        raise AgentInstallError(f"empty agent prompt source for {spec.name}: {spec.prompt_source}")
    lines = [
        spec.marker,
        f"name = {_toml_string(spec.name)}",
        f"description = {_toml_string(spec.description)}",
        f"model_reasoning_effort = {_toml_string(spec.model_reasoning_effort)}",
        f"developer_instructions = {_toml_string(prompt)}",
        "",
    ]
    return "\n".join(lines)


def codex_home_from(codex_home: Path | None = None, target_repo: Path | None = None) -> Path:
    if codex_home is not None and target_repo is not None:
        raise AgentInstallError("pass only one of --codex-home or --target-repo")
    if codex_home is not None:
        return codex_home.expanduser().resolve()
    if target_repo is not None:
        return (target_repo.resolve() / ".codex")
    return (Path.home() / ".codex").resolve()


def target_agents_dir(codex_home: Path | None = None, target_repo: Path | None = None) -> Path:
    return codex_home_from(codex_home, target_repo) / AGENT_DIR


def is_managed_agent_file(path: Path, spec: AgentSpec) -> bool:
    if not path.exists():
        return False
    first = path.read_text().splitlines()[:1]
    return bool(first and first[0].strip() == spec.marker)


def sweep_obsolete_agents(agents_dir: Path) -> list[Path]:
    """Managed agent files that no current spec claims.

    Replaces a hardcoded rename list: any file we previously wrote is obsolete
    once it drops out of AGENT_SPECS, so match on the marker instead.
    """
    if not agents_dir.is_dir():
        return []
    current = {spec.filename for spec in AGENT_SPECS}
    obsolete: list[Path] = []
    for path in sorted(agents_dir.glob(MANAGED_GLOB)):
        if path.name in current:
            continue
        first = path.read_text().splitlines()[:1]
        if first and first[0].strip().startswith(MANAGED_MARKER_PREFIX):
            obsolete.append(path)
    return obsolete


def install_agents(*, codex_home: Path | None = None, target_repo: Path | None = None, force: bool = False, root: Path | None = None) -> list[dict[str, str]]:
    agents_dir = target_agents_dir(codex_home, target_repo)
    agents_dir.mkdir(parents=True, exist_ok=True)
    for obsolete_path in sweep_obsolete_agents(agents_dir):
        obsolete_path.unlink()
    installed: list[dict[str, str]] = []
    for spec in AGENT_SPECS:
        path = agents_dir / spec.filename
        if path.exists() and not force and not is_managed_agent_file(path, spec):
            raise AgentInstallError(f"unmanaged agent file exists: {path}")
        rendered = render_agent_toml(spec, root=root)
        path.write_text(rendered)
        installed.append({"name": spec.name, "path": str(path), "prompt_source": spec.prompt_source})
    return installed


def check_agents(*, codex_home: Path | None = None, target_repo: Path | None = None, root: Path | None = None) -> dict[str, Any]:
    agents_dir = target_agents_dir(codex_home, target_repo)
    records = []
    ok = True
    for spec in AGENT_SPECS:
        path = agents_dir / spec.filename
        expected = render_agent_toml(spec, root=root)
        if not path.exists():
            status = "missing"
            ok = False
        elif not is_managed_agent_file(path, spec):
            status = "unmanaged_conflict"
            ok = False
        elif path.read_text() != expected:
            status = "stale"
            ok = False
        else:
            status = "ok"
        records.append({"name": spec.name, "path": str(path), "prompt_source": spec.prompt_source, "status": status})
    return {"ok": ok, "agents_dir": str(agents_dir), "agents": records}


def list_agents() -> list[dict[str, str]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "prompt_source": spec.prompt_source,
            "model_reasoning_effort": spec.model_reasoning_effort,
        }
        for spec in AGENT_SPECS
    ]

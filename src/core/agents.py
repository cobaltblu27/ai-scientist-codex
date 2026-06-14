"""Generated Codex native-agent registry for AI Scientist subagents."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.plugin import plugin_root

MANAGED_MARKER_PREFIX = "# ai-scientist agent: "
AGENT_DIR = "agents"


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
    specs: list[AgentSpec] = []
    for mode in ("scientist", "engineer", "custom"):
        specs.append(
            AgentSpec(
                name=f"ai-scientist-ideation-generator-{mode}",
                description=f"AI Scientist ideation generator for {mode} mode.",
                prompt_source=f"prompts/ideation/{mode}/generator.md",
                model_reasoning_effort="xhigh",
            )
        )
        specs.append(
            AgentSpec(
                name=f"ai-scientist-ideation-critic-{mode}",
                description=f"AI Scientist ideation critic for {mode} mode.",
                prompt_source=f"prompts/ideation/{mode}/critic.md",
                model_reasoning_effort="high",
            )
        )
        specs.append(
            AgentSpec(
                name=f"ai-scientist-research-critic-{mode}",
                description=f"AI Scientist research critic for {mode} mode.",
                prompt_source=f"prompts/research-loop/{mode}/critic.md",
                model_reasoning_effort="high",
            )
        )
        specs.append(
            AgentSpec(
                name=f"ai-scientist-research-revision-worker-{mode}",
                description=f"AI Scientist research revision worker for {mode} mode.",
                prompt_source=f"prompts/research-loop/{mode}/revision-worker.md",
                model_reasoning_effort="high",
            )
        )
    specs.extend(
        [
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
                model_reasoning_effort="high",
            ),
        ]
    )
    return sorted(specs, key=lambda spec: spec.name)


AGENT_SPECS: tuple[AgentSpec, ...] = tuple(_specs())


def agent_names() -> list[str]:
    return [spec.name for spec in AGENT_SPECS]


def ideation_agent_name(mode: str, role: str) -> str:
    if mode not in {"scientist", "engineer", "custom"}:
        raise AgentInstallError(f"invalid ideation mode: {mode}")
    if role not in {"generator", "critic"}:
        raise AgentInstallError(f"invalid ideation agent role: {role}")
    return f"ai-scientist-ideation-{role}-{mode}"


def research_agent_name(mode: str, role: str) -> str:
    if role == "baseline-worker":
        return "ai-scientist-research-baseline-worker"
    if role == "worker":
        return "ai-scientist-research-worker"
    if mode not in {"scientist", "engineer", "custom"}:
        raise AgentInstallError(f"invalid research mode: {mode}")
    if role == "critic":
        return f"ai-scientist-research-critic-{mode}"
    if role == "revision-worker":
        return f"ai-scientist-research-revision-worker-{mode}"
    raise AgentInstallError(f"invalid research agent role: {role}")


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


def install_agents(*, codex_home: Path | None = None, target_repo: Path | None = None, force: bool = False, root: Path | None = None) -> list[dict[str, str]]:
    agents_dir = target_agents_dir(codex_home, target_repo)
    agents_dir.mkdir(parents=True, exist_ok=True)
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

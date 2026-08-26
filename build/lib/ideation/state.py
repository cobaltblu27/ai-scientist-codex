#!/usr/bin/env python3
"""Ledger helpers for goal-driven AI Scientist ideation.

This module deliberately does not spawn Codex or own an ideation loop. The
current Codex session is the orchestrator; these helpers persist run artifacts,
track pending subagent work, and validate the final handoff schema.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.agents import ideation_agent_name
from core.plugin import plugin_root
from core.state import (
    ai_root,
    append_journal_event,
    atomic_write_json,
    config_path,
    data_hash,
    has_substantive_value,
    load_json_if_exists,
    load_loop_state,
    mutate_loop_state,
    run_dir,
    set_active_run,
    start_phase,
    utc_now,
)

MODES = {"scientist", "engineer", "custom"}
INTENT_ROLES = {"generator", "critic", "selector", "schema_builder"}
PROMPT_ROLES = ("generator", "critic")
TERMINAL_IDEA_STATUSES = {"selected", "error"}
TERMINAL_IDEATION_STATUSES = {"COMPLETED", "EXHAUSTED_NO_CANDIDATE", "CANCELLED"}
SUCCESS_TERMINAL_STATUSES = {"COMPLETED"}
IDEA_OUTPUT_SCHEMA = {
    "required": [
        "id",
        "family_key",
        "title",
        "hypothesis",
        "unique_protocol",
        "expected_metric",
        "mechanism",
        "implementation_sketch",
        "expected_metric_effect",
        "fit_to_research_contract",
        "novelty_angle",
        "smoke_runnable_now",
        "requires_implementation",
        "minimum_command",
        "evidence_refs",
        "rubric_scores",
        "risk_flags",
    ]
}
RESEARCH_CONTRACT_REQUIRED_FIELDS = {
    "primary_hypothesis",
    "goal_type",
    "success_criteria",
    "failure_criteria",
    "allowed_rescue_scope",
    "kill_criteria",
    "non_drift_definition",
    "metrics_that_matter",
    "non_negotiable_comparisons",
}
PERFORMANCE_GOAL_TERMS = {"performance", "model_performance", "enhanced_model_performance", "benchmarking"}
CAMPAIGN_CONTRACT_REQUIREMENT_GROUPS = {
    "fixed_dataset": ("fixed_dataset", "dataset", "dataset_ref"),
    "fixed_split": ("fixed_split", "split_protocol", "split_ref", "fixed_split_ref"),
    "fixed_baseline": ("fixed_baseline", "baseline_reference", "baseline_ref"),
    "metrics": ("metrics_that_matter", "metrics", "metric"),
    "evaluator_command": ("evaluator_command", "evaluator", "benchmark_command", "benchmark_plan"),
}


def prompt_path_for(mode: str, role: str) -> str:
    if mode not in MODES:
        raise IdeationStateError(f"invalid ideation mode: {mode}")
    if role not in PROMPT_ROLES:
        raise IdeationStateError(f"invalid ideation prompt role: {role}")
    return f"prompts/ideation/{mode}/{role}.md"


def default_prompt_refs(mode: str) -> dict[str, str]:
    return {
        "generator_agent": ideation_agent_name(mode, "generator"),
        "generator_prompt_source": prompt_path_for(mode, "generator"),
        "critic_agent": ideation_agent_name(mode, "critic"),
        "critic_prompt_source": prompt_path_for(mode, "critic"),
    }


DEFAULT_MODE_PRESETS: dict[str, dict[str, Any]] = {
    "scientist": {
        "scoring_weights": {"novelty": 0.35, "evidence": 0.25, "feasibility": 0.20, "repo_fit": 0.20},
        **default_prompt_refs("scientist"),
    },
    "engineer": {
        "scoring_weights": {"performance": 0.45, "feasibility": 0.30, "repo_fit": 0.20, "novelty": 0.05},
        **default_prompt_refs("engineer"),
    },
    "custom": {
        "scoring_weights": {"custom_fit": 0.40, "feasibility": 0.30, "repo_fit": 0.20, "evidence": 0.10},
        **default_prompt_refs("custom"),
    },
}


DEFAULT_IDEATION_CONFIG: dict[str, Any] = {
    "default_mode": "scientist",
    "num_ideas_required": 10,
    "min_candidates_required": 1,
    "prompt_root": "prompts/ideation",
    "concurrency": {"max_subagents": 6},
    "modes": DEFAULT_MODE_PRESETS,
}


class IdeationStateError(Exception):
    pass


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged

def run_ideas_path(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "ideas.json"


def run_logs_dir(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id) / "logs"


def ideation_contract_path(target_repo: Path, run_id: str) -> Path:
    return run_logs_dir(target_repo, run_id) / "ideation-contract.json"


def pending_result_path(target_repo: Path, run_id: str, intent_id: str) -> Path:
    return run_logs_dir(target_repo, run_id) / "pending" / f"{intent_id}.json"


def load_payload_from_args(json_value: str | None = None, path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        payload = json.loads(path.read_text())
    elif json_value:
        payload = json.loads(json_value)
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise IdeationStateError("payload must be a JSON object")
    return payload


def load_plugin_config() -> dict[str, Any]:
    path = plugin_root() / "config" / "config.json"
    value = load_json_if_exists(path)
    return value if isinstance(value, dict) else {}


def load_project_override(target_repo: Path) -> dict[str, Any]:
    value = load_json_if_exists(ai_root(target_repo) / "config.json")
    return value if isinstance(value, dict) else {}


def nested_value(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def codex_max_threads(target_repo: Path) -> int | None:
    candidates = [
        target_repo / ".codex" / "config.toml",
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        section = None
        for raw_line in path.read_text().splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line.strip("[]").strip()
                continue
            if section == "agents" and line.startswith("max_threads"):
                key, _, value = line.partition("=")
                if key.strip() != "max_threads":
                    continue
                parsed = int(value.strip())
                if parsed > 0:
                    return parsed
    return None


def validate_max_subagents(value: Any) -> int:
    if not isinstance(value, int) or value <= 0:
        raise IdeationStateError("ideation.concurrency.max_subagents must be a positive integer")
    return value


def validate_positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise IdeationStateError(f"{name} must be a positive integer")
    return value


def choose_mode(config: dict[str, Any], requested_mode: str | None) -> str:
    ideation = config.get("ideation") if isinstance(config.get("ideation"), dict) else {}
    mode = requested_mode or config.get("strictness_mode") or ideation.get("default_mode") or "scientist"
    if mode not in MODES:
        raise IdeationStateError(f"invalid ideation mode: {mode}")
    return str(mode)


def validate_mode_preset(config: dict[str, Any], mode: str) -> dict[str, Any]:
    ideation = config.get("ideation") if isinstance(config.get("ideation"), dict) else {}
    modes = ideation.get("modes") if isinstance(ideation.get("modes"), dict) else {}
    preset = modes.get(mode)
    if not isinstance(preset, dict):
        raise IdeationStateError(f"missing ideation preset for mode: {mode}")
    for key in ("generator_agent", "critic_agent"):
        if not isinstance(preset.get(key), str) or not preset[key].strip():
            raise IdeationStateError(f"ideation preset {mode} missing {key}")
    return preset


def validate_ideation_prompt_files(config: dict[str, Any], mode: str) -> None:
    preset = validate_mode_preset(config, mode)
    root = plugin_root()
    for key in ("generator_prompt_source", "critic_prompt_source"):
        value = str(preset.get(key) or preset.get(key.replace("_source", "")) or "")
        if not value:
            raise IdeationStateError(f"ideation preset {mode} missing {key}")
        path = root / value
        if not path.exists():
            raise IdeationStateError(f"missing ideation prompt file for {mode} {key}: {value}")
        if not path.is_file() or not path.read_text().strip():
            raise IdeationStateError(f"empty ideation prompt file for {mode} {key}: {value}")


def frozen_config(
    target_repo: Path,
    run_id: str,
    requested_mode: str | None,
    *,
    num_ideas_required: int | None = None,
    min_candidates_required: int | None = None,
    max_subagents: int | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "ideation": DEFAULT_IDEATION_CONFIG,
        "api_budgets": {},
        "workspace": {"mode": "copy"},
        "dependency_plan": {"mode": "frozen", "planned_dependencies": []},
        "benchmark_contract": {"version": "ideation-v1", "command": None},
        "resources": {"gpu": {"mode": "not_applicable_ideation"}},
        "selection": {"good_enough_score_threshold": 75},
    }
    plugin_cfg = load_plugin_config()
    project_override = load_project_override(target_repo)
    merged = deep_merge(base, plugin_cfg)
    merged = deep_merge(merged, project_override)
    mode = choose_mode(merged, requested_mode)
    ideation_cfg = merged.setdefault("ideation", {})
    concurrency_cfg = ideation_cfg.setdefault("concurrency", {})
    project_max = nested_value(project_override, ["ideation", "concurrency", "max_subagents"])
    resolved_max = max_subagents
    if resolved_max is None:
        resolved_max = project_max if project_max is not None else codex_max_threads(target_repo)
    if resolved_max is None:
        resolved_max = concurrency_cfg.get("max_subagents", 6)
    concurrency_cfg["max_subagents"] = validate_max_subagents(resolved_max)
    if num_ideas_required is not None:
        ideation_cfg["num_ideas_required"] = num_ideas_required
    if min_candidates_required is not None:
        ideation_cfg["min_candidates_required"] = min_candidates_required
    ideation_cfg.pop("reflection_budget", None)
    ideation_cfg.pop("reflection_budget_per_idea", None)
    ideation_cfg.pop("max_attempts_per_slot", None)
    ideation_cfg.pop("early_stop_allowed", None)
    validate_ideation_prompt_files(merged, mode)
    merged.update(
        {
            "schema_version": 1,
            "run_id": run_id,
            "target_repo": str(target_repo.resolve()),
            "strictness_mode": mode,
            "created_at": utc_now(),
        }
    )
    return merged


def mode_preset(config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("strictness_mode") or "scientist")
    return validate_mode_preset(config, mode)


def idea_states(state: dict[str, Any]) -> dict[str, Any]:
    phase_state = state.setdefault("state", {})
    ideas = phase_state.setdefault("idea_states", {})
    if not isinstance(ideas, dict):
        raise IdeationStateError("loop-state.json state.idea_states must be an object")
    return ideas


def current_config(target_repo: Path, run_id: str) -> dict[str, Any]:
    cfg = load_json_if_exists(config_path(target_repo, run_id))
    if not isinstance(cfg, dict):
        raise IdeationStateError(f"missing run config.json for ideation run {run_id}")
    return cfg


def slug_key(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or "idea"


def as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def summarize_protocol(payload: dict[str, Any]) -> str:
    value = payload.get("unique_protocol")
    if isinstance(value, str) and value.strip():
        return value.strip()
    experiments = payload.get("experiments")
    if isinstance(experiments, list) and experiments:
        return " | ".join(str(item) for item in experiments[:3])
    plan = payload.get("execution_plan")
    if isinstance(plan, list) and plan:
        parts = []
        for item in plan[:3]:
            if isinstance(item, dict):
                parts.append(str(item.get("step") or item.get("method") or item))
            else:
                parts.append(str(item))
        return " | ".join(parts)
    hypothesis = payload.get("hypothesis")
    return str(hypothesis or "protocol to be specified").strip()


def compact_idea_payload(payload: dict[str, Any], idea_id: str, run_id: str) -> dict[str, Any]:
    title = str(payload.get("title") or payload.get("Name") or payload.get("Title") or f"Idea {idea_id}").strip()
    hypothesis = str(payload.get("hypothesis") or payload.get("Short Hypothesis") or payload.get("abstract") or "").strip()
    if not hypothesis:
        raise IdeationStateError("idea draft must include hypothesis or abstract")
    expected_metric = str(payload.get("expected_metric") or payload.get("metric") or "score").strip()
    requires_implementation = as_string_list(payload.get("requires_implementation"))
    evidence_refs = as_string_list(payload.get("evidence_refs"))
    rubric_scores = payload.get("rubric_scores")
    if not isinstance(rubric_scores, dict):
        rubric_scores = {}
    risk_flags = as_string_list(payload.get("risk_flags")) or as_string_list(payload.get("risks"))
    minimum_command = payload.get("minimum_command")
    if minimum_command is not None:
        minimum_command = str(minimum_command).strip() or None
    family_key = str(payload.get("family_key") or slug_key(title or hypothesis)).strip()
    compact = {
        "id": idea_id,
        "family_key": family_key,
        "title": title,
        "hypothesis": hypothesis,
        "unique_protocol": summarize_protocol(payload),
        "expected_metric": expected_metric,
        "mechanism": payload.get("mechanism"),
        "implementation_sketch": payload.get("implementation_sketch"),
        "expected_metric_effect": payload.get("expected_metric_effect"),
        "fit_to_research_contract": payload.get("fit_to_research_contract"),
        "novelty_angle": payload.get("novelty_angle"),
        "smoke_runnable_now": bool(payload.get("smoke_runnable_now")),
        "requires_implementation": requires_implementation,
        "minimum_command": minimum_command,
        "evidence_refs": evidence_refs,
        "rubric_scores": {str(key): value for key, value in rubric_scores.items()},
        "risk_flags": risk_flags,
        "source_run_id": str(payload.get("source_run_id") or run_id),
    }
    for aliases in CAMPAIGN_CONTRACT_REQUIREMENT_GROUPS.values():
        for key in aliases:
            if key in payload:
                compact[key] = deepcopy(payload[key])
    return compact


def pyproject_commands(target_repo: Path) -> list[str]:
    path = target_repo / "pyproject.toml"
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    commands = ["uv run python -m pytest", "uv run pytest"]
    scripts = data.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict):
        commands.extend(sorted(str(name) for name in scripts))
        commands.extend(sorted(f"uv run {name}" for name in scripts))
    return commands


def makefile_commands(target_repo: Path) -> list[str]:
    commands: list[str] = []
    for name in ("Makefile", "makefile"):
        path = target_repo / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+):(?:\s|$)", line)
            if match and not match.group(1).startswith("."):
                commands.append(f"make {match.group(1)}")
    return commands


def package_json_commands(target_repo: Path) -> list[str]:
    path = target_repo / "package.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    scripts = data.get("scripts") if isinstance(data, dict) else {}
    if not isinstance(scripts, dict):
        return []
    return sorted(f"npm run {name}" for name in scripts)


def shell_script_commands(target_repo: Path) -> list[str]:
    commands: list[str] = []
    for path in target_repo.glob("*.sh"):
        if path.is_file():
            commands.append(f"./{path.name}")
    scripts_dir = target_repo / "scripts"
    if scripts_dir.is_dir():
        for path in scripts_dir.glob("*.sh"):
            if path.is_file():
                commands.append(f"./scripts/{path.name}")
    return sorted(commands)


def discover_repo_contract(target_repo: Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    commands = sorted(set(pyproject_commands(target_repo) + makefile_commands(target_repo) + package_json_commands(target_repo) + shell_script_commands(target_repo)))
    benchmark_command = nested_value(config, ["benchmark_contract", "command"])
    if isinstance(benchmark_command, str) and benchmark_command.strip():
        commands.append(benchmark_command.strip())
    split_files = sorted(str(path.relative_to(target_repo)) for path in target_repo.rglob("*") if path.is_file() and "split" in path.name.lower() and ".ai-scientist" not in path.parts)
    config_files = sorted(str(path.relative_to(target_repo)) for path in target_repo.iterdir() if path.is_file() and path.name in {"pyproject.toml", "uv.lock", "environment.yml", "environment.yaml", "requirements.txt", "package.json", "Makefile"})
    return {
        "schema_version": 1,
        "run_id": run_id,
        "strictness_mode": config.get("strictness_mode"),
        "repo_entrypoints": commands,
        "benchmark_split_policy": {"split_files": split_files, "policy": "preserve existing repository split/config unless explicitly changed in research-loop contract"},
        "hardware_limits": {"gpu": "single RTX3070", "memory_gb": 32},
        "forbidden_workflows": ["changing Python/PyTorch/CUDA/runtime versions during ideation", "using hidden data leakage", "changing benchmark splits without explicit research-loop approval"],
        "reusable_baselines": [{"command": benchmark_command}] if isinstance(benchmark_command, str) and benchmark_command.strip() else [],
        "metric_names": [],
        "config_files": config_files,
    }


def load_ideation_contract(target_repo: Path, run_id: str) -> dict[str, Any]:
    value = load_json_if_exists(ideation_contract_path(target_repo, run_id))
    return value if isinstance(value, dict) else {}


def command_matches_known(command: str, known_commands: list[str]) -> bool:
    normalized = " ".join(command.split())
    for known in known_commands:
        known_normalized = " ".join(str(known).split())
        if normalized == known_normalized or normalized.startswith(f"{known_normalized} "):
            return True
    return False


def validate_minimum_command(idea: dict[str, Any], contract: dict[str, Any]) -> None:
    command = idea.get("minimum_command")
    smoke_runnable = idea.get("smoke_runnable_now") is True
    requires_impl = as_string_list(idea.get("requires_implementation"))
    if smoke_runnable:
        if not isinstance(command, str) or not command.strip():
            raise IdeationStateError("smoke_runnable_now requires minimum_command")
        known = [str(item) for item in contract.get("repo_entrypoints", []) if isinstance(item, str)]
        if known and not command_matches_known(command, known):
            raise IdeationStateError(f"minimum_command_not_known_entrypoint:{command}")
    placeholder = isinstance(command, str) and bool(re.search(r"\b(TODO|TBD|placeholder|future|hook)\b", command, re.IGNORECASE))
    if (placeholder or (command and not smoke_runnable)) and not requires_impl:
        raise IdeationStateError("non-runnable or placeholder command requires requires_implementation")


def validate_family_dedup(phase_state: dict[str, Any], candidate_id: str) -> None:
    ideas = phase_state.setdefault("idea_states", {})
    candidate = ideas.get(candidate_id)
    if not isinstance(candidate, dict):
        raise IdeationStateError(f"unknown idea_id: {candidate_id}")
    draft = candidate.get("latest_draft") if isinstance(candidate.get("latest_draft"), dict) else {}
    for idea_id, idea in ideas.items():
        if idea_id == candidate_id or not isinstance(idea, dict):
            continue
        if str(idea.get("status") or "") not in {"accepted", "accepted_without_reference"}:
            continue
        other = idea.get("latest_draft") if isinstance(idea.get("latest_draft"), dict) else {}
        if (
            draft.get("family_key")
            and draft.get("family_key") == other.get("family_key")
            and draft.get("unique_protocol") == other.get("unique_protocol")
            and draft.get("expected_metric") == other.get("expected_metric")
        ):
            raise IdeationStateError(f"duplicate_idea_family:{candidate_id}:{idea_id}")


def contract_goal_type(contract: dict[str, Any]) -> str:
    return str(contract.get("goal_type") or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_performance_contract(contract: dict[str, Any]) -> bool:
    goal_type = contract_goal_type(contract)
    return goal_type in PERFORMANCE_GOAL_TERMS or "performance" in goal_type


def contract_has_baseline_reference(contract: dict[str, Any]) -> bool:
    baseline = contract.get("baseline_reference")
    if not isinstance(baseline, dict) or not baseline:
        return False
    if not has_substantive_value(baseline.get("usability")):
        return False
    return any(has_substantive_value(baseline.get(key)) for key in ("title", "paper", "model", "source", "citation", "url", "doi"))


def validate_research_contract(contract: Any, *, require_performance_baseline: bool = True) -> None:
    if not isinstance(contract, dict) or not contract:
        raise IdeationStateError("research_contract_required")
    missing = sorted(key for key in RESEARCH_CONTRACT_REQUIRED_FIELDS if not has_substantive_value(contract.get(key)))
    if missing:
        raise IdeationStateError(f"research_contract_missing_fields:{','.join(missing)}")
    if not has_substantive_value(contract.get("success_criteria")):
        raise IdeationStateError("research_contract_success_criteria_required")
    if is_performance_contract(contract):
        if require_performance_baseline and not contract_has_baseline_reference(contract):
            raise IdeationStateError("performance_contract_baseline_reference_required")
        if require_performance_baseline and not has_substantive_value(contract.get("benchmark_plan")):
            raise IdeationStateError("performance_contract_benchmark_plan_required")
        if require_performance_baseline and not has_substantive_value(contract.get("target_threshold")):
            raise IdeationStateError("performance_contract_target_threshold_required")


def first_substantive_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if has_substantive_value(value):
            return value
    return None


def normalize_contract_value(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True).lower()
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True).lower()
    return str(value or "").strip().lower()


def validate_campaign_research_contract(contract: Any) -> None:
    validate_research_contract(contract, require_performance_baseline=True)
    if not isinstance(contract, dict) or not is_performance_contract(contract):
        raise IdeationStateError("campaign_research_contract_goal_type_must_be_performance")
    missing = sorted(name for name, aliases in CAMPAIGN_CONTRACT_REQUIREMENT_GROUPS.items() if not has_substantive_value(first_substantive_value(contract, aliases)))
    if missing:
        raise IdeationStateError(f"campaign_research_contract_missing_fields:{','.join(missing)}")


def run_research_contract(config: dict[str, Any]) -> dict[str, Any]:
    contract = config.get("research_contract")
    return contract if isinstance(contract, dict) else {}


def validate_idea_fits_campaign(draft: dict[str, Any], campaign_contract: dict[str, Any]) -> None:
    if not has_substantive_value(draft.get("fit_to_research_contract")):
        raise IdeationStateError("idea_fit_to_research_contract_required")
    for name, aliases in CAMPAIGN_CONTRACT_REQUIREMENT_GROUPS.items():
        campaign_value = first_substantive_value(campaign_contract, aliases)
        draft_value = first_substantive_value(draft, aliases)
        if draft_value is None or campaign_value is None:
            continue
        if normalize_contract_value(draft_value) != normalize_contract_value(campaign_value):
            raise IdeationStateError(f"idea_changes_campaign_{name}")


def terminal_ideas(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    for idea in idea_states(state).values():
        if isinstance(idea, dict) and str(idea.get("status") or "") in TERMINAL_IDEA_STATUSES:
            values.append(idea)
    return sorted(values, key=lambda item: int(item.get("slot_index") or 0))


def is_researchable_idea(idea: dict[str, Any], config: dict[str, Any]) -> bool:
    return str(idea.get("evaluation") or "").upper() == "ACCEPTED"


def researchable_candidates(state: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    return [idea for idea in terminal_ideas(state) if is_researchable_idea(idea, config)]


def new_idea_slot(idea_id: str, slot_index: int) -> dict[str, Any]:
    return {
        "id": idea_id,
        "slot_index": slot_index,
        "status": "drafting",
        "source_run_id": None,
        "artifacts": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def next_idea_id(phase_state: dict[str, Any]) -> str:
    return f"idea-{int(phase_state.get('attempted_slots') or 0) + 1:03d}"


def max_subagents(config: dict[str, Any]) -> int:
    ideation = config.get("ideation") if isinstance(config.get("ideation"), dict) else {}
    concurrency = ideation.get("concurrency") if isinstance(ideation.get("concurrency"), dict) else {}
    return validate_max_subagents(concurrency.get("max_subagents", 6))


def pending_intents(phase_state: dict[str, Any]) -> dict[str, Any]:
    pending = phase_state.setdefault("pending_intents", {})
    if not isinstance(pending, dict):
        raise IdeationStateError("loop-state.json state.pending_intents must be an object")
    legacy = phase_state.get("pending_intent")
    if isinstance(legacy, dict) and isinstance(legacy.get("intent_id"), str):
        pending.setdefault(legacy["intent_id"], legacy)
        phase_state["pending_intent"] = None
    return pending


def active_idea_ids(phase_state: dict[str, Any]) -> list[str]:
    active = phase_state.setdefault("active_idea_ids", [])
    if not isinstance(active, list):
        raise IdeationStateError("loop-state.json state.active_idea_ids must be a list")
    legacy = phase_state.get("active_idea_id")
    if isinstance(legacy, str) and legacy and legacy not in active:
        active.append(legacy)
        phase_state["active_idea_id"] = None
    return [str(item) for item in active if isinstance(item, str) and item]


def add_active_idea(phase_state: dict[str, Any], idea_id: str) -> None:
    active = phase_state.setdefault("active_idea_ids", [])
    if idea_id not in active:
        active.append(idea_id)


def remove_active_idea(phase_state: dict[str, Any], idea_id: str) -> None:
    phase_state["active_idea_ids"] = [item for item in active_idea_ids(phase_state) if item != idea_id]


def resolve_idea_id(phase_state: dict[str, Any], explicit_idea_id: str | None, action: str) -> str:
    if explicit_idea_id:
        return explicit_idea_id
    active = active_idea_ids(phase_state)
    if len(active) == 1:
        return active[0]
    if not active:
        raise IdeationStateError(f"{action} requires an active idea or --idea-id")
    raise IdeationStateError(f"{action} requires --idea-id when multiple ideas are active")


def cursor_for_state(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    return {
        "next_action": None,
        "next_action_details": {
            "reason": "goal_driven_ideation",
            "pending_count": len(pending_intents(phase_state)),
            "selected_count": len(researchable_candidates(state, config or {})),
        },
    }


def update_cursor(state: dict[str, Any], config: dict[str, Any] | None = None) -> None:
    phase_state = state.setdefault("state", {})
    orchestrator = phase_state.setdefault("orchestrator", {})
    orchestrator["control"] = "create_goal"
    orchestrator.pop("next_action", None)
    orchestrator.pop("next_action_details", None)
    orchestrator["last_checkpoint_at"] = utc_now()


def public_idea_record(idea: dict[str, Any]) -> dict[str, Any]:
    latest_draft = idea.get("latest_draft") if isinstance(idea.get("latest_draft"), dict) else {}
    compact = {key: latest_draft.get(key) for key in IDEA_OUTPUT_SCHEMA["required"] if key in latest_draft}
    return {
        "id": idea.get("id"),
        "status": idea.get("status"),
        "evaluation": idea.get("evaluation"),
        "rank": idea.get("rank"),
        "score": idea.get("score"),
        "score_components": idea.get("score_components"),
        "rationale": idea.get("rationale"),
        "risk_flags": idea.get("risk_flags"),
        "selected": idea.get("selected") is True,
        "researchable": idea.get("researchable") is True,
        "source_run_id": idea.get("source_run_id"),
        "draft_version": idea.get("draft_version"),
        "idea_hash": idea.get("idea_hash"),
        "manual_selection_only": idea.get("manual_selection_only"),
        "draft_ref": idea.get("draft_ref"),
        "critic_refs": idea.get("critic_refs") if isinstance(idea.get("critic_refs"), list) else [],
        "selector_refs": idea.get("selector_refs") if isinstance(idea.get("selector_refs"), list) else [],
        "risks": latest_draft.get("risk_flags", []),
        "normalized": compact,
        "upstream": compact,
        **compact,
    }


def sync_ideas_archive(target_repo: Path, run_id: str, state: dict[str, Any]) -> None:
    records = [public_idea_record(idea) for idea in terminal_ideas(state)]
    atomic_write_json(run_ideas_path(target_repo, run_id), {"schema_version": 1, "run_id": run_id, "ideas": records, "updated_at": utc_now()})


def write_payload_log(target_repo: Path, run_id: str, subdir: str, filename: str, payload: dict[str, Any]) -> Path:
    path = run_logs_dir(target_repo, run_id) / subdir / filename
    atomic_write_json(path, payload)
    return path


def write_text_log(target_repo: Path, run_id: str, subdir: str, filename: str, text: str) -> Path:
    path = run_logs_dir(target_repo, run_id) / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def increment_iteration(phase_state: dict[str, Any]) -> None:
    phase_state["iterations_used"] = int(phase_state.get("iterations_used") or 0) + 1


def ensure_active_ideation_state(target_repo: Path, run_id: str) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not isinstance(state, dict):
        raise IdeationStateError(f"missing loop-state.json for run {run_id}")
    if state.get("phase") != "ideation":
        raise IdeationStateError(f"run {run_id} is not an ideation run")
    return state


def start_ideation(
    target_repo: Path,
    run_id: str,
    prompt: str,
    *,
    mode: str | None = None,
    num_ideas_required: int | None = None,
    min_candidates_required: int | None = None,
    max_subagents: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if load_loop_state(target_repo, run_id):
        raise IdeationStateError(f"ideation run already exists: {run_id}")
    if not prompt.strip():
        raise IdeationStateError("ideation prompt is required")
    payload = payload or {}
    research_contract = payload.get("research_contract")
    validate_campaign_research_contract(research_contract)
    cfg = frozen_config(
        target_repo,
        run_id,
        mode,
        num_ideas_required=num_ideas_required,
        min_candidates_required=min_candidates_required,
        max_subagents=max_subagents,
    )
    cfg["research_contract"] = deepcopy(research_contract)
    ideation_cfg = cfg["ideation"]
    initial = {
        "prompt": prompt,
        "mode": cfg["strictness_mode"],
        "orchestrator": {"role": "main_codex_session", "iteration": 0},
        "num_ideas_required": int(ideation_cfg.get("num_ideas_required") or 10),
        "min_candidates_required": int(ideation_cfg.get("min_candidates_required") or 1),
        "attempted_slots": 0,
        "iterations_used": 0,
        "active_idea_ids": [],
        "pending_intents": {},
        "intents": {},
        "batches": [],
        "idea_states": {},
        "artifacts": {"idea_batches": [], "critic_feedback": [], "selector_reports": [], "final_schema": None},
        "research_contract": deepcopy(research_contract),
        "handoff": {"status": "pending", "candidates": []},
    }
    state = start_phase(target_repo, run_id, "ideation", initial)
    update_cursor(state, cfg)
    atomic_write_json(config_path(target_repo, run_id), cfg)
    atomic_write_json(ideation_contract_path(target_repo, run_id), discover_repo_contract(target_repo, run_id, cfg))
    atomic_write_json(run_ideas_path(target_repo, run_id), {"schema_version": 1, "run_id": run_id, "ideas": [], "updated_at": utc_now()})
    atomic_write_json(run_dir(target_repo, run_id) / "loop-state.json", state)
    append_journal_event(target_repo, run_id, "state_transition", details={"command": "ideation start", "prompt": prompt, "mode": cfg["strictness_mode"], "state_hash": data_hash(state)})
    return state


def resume_ideation(target_repo: Path, run_id: str, *, prompt: bool = False) -> dict[str, Any]:
    state = ensure_active_ideation_state(target_repo, run_id)
    cfg = current_config(target_repo, run_id)
    update_cursor(state, cfg)
    atomic_write_json(run_dir(target_repo, run_id) / "loop-state.json", state)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    summary = cursor_for_state(state, cfg)["next_action_details"]
    append_journal_event(target_repo, run_id, "state_transition", details={"command": "ideation resume", **summary})
    response = {"run_id": run_id, "phase_status": state.get("phase_status"), "summary": summary}
    if prompt:
        response["prompt"] = orchestration_prompt(state, cfg)
    return response


def orchestration_prompt(state: dict[str, Any], config: dict[str, Any]) -> str:
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    preset = mode_preset(config)
    lines = [
        "You are the main Codex ideation orchestrator for AI Scientist.",
        "Do not run a Python ideation orchestrator or nested codex exec.",
        f"Run id: {state.get('run_id')}",
        f"Mode: {config.get('strictness_mode')}",
        f"Run-owned research contract: {json.dumps(config.get('research_contract') or {}, sort_keys=True)}",
        f"Shared contract: {ideation_contract_path(Path(str(config.get('target_repo'))), str(state.get('run_id')))}",
        "Control: create_goal owns continuation. Use the ideation skill workflow.",
        f"Pending intents: {len(pending_intents(phase_state))}",
        f"Selected ideas: {len(researchable_candidates(state, config))}",
        f"Generator agent_type: {preset['generator_agent']}",
        f"Critic agent_type: {preset['critic_agent']}",
    ]
    lines.append(f"Original topic: {phase_state.get('prompt')}")
    return "\n".join(lines)


def allocate_idea_if_needed(phase_state: dict[str, Any], idea_id: str | None = None) -> str:
    ideas = phase_state.setdefault("idea_states", {})
    if idea_id:
        if idea_id not in ideas:
            phase_state["attempted_slots"] = int(phase_state.get("attempted_slots") or 0) + 1
            ideas[idea_id] = new_idea_slot(idea_id, int(phase_state["attempted_slots"]))
        add_active_idea(phase_state, idea_id)
        return idea_id
    active = active_idea_ids(phase_state)
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        raise IdeationStateError("idea_id is required when multiple ideas are active")
    required = int(phase_state.get("num_ideas_required") or 0)
    attempted = int(phase_state.get("attempted_slots") or 0)
    if attempted >= required:
        raise IdeationStateError("no idea slots remain")
    new_id = next_idea_id(phase_state)
    phase_state["attempted_slots"] = attempted + 1
    ideas[new_id] = new_idea_slot(new_id, int(phase_state["attempted_slots"]))
    add_active_idea(phase_state, new_id)
    return new_id


def allocate_new_idea(phase_state: dict[str, Any]) -> str:
    ideas = phase_state.setdefault("idea_states", {})
    required = int(phase_state.get("num_ideas_required") or 0)
    attempted = int(phase_state.get("attempted_slots") or 0)
    if attempted >= required:
        raise IdeationStateError("no idea slots remain")
    new_id = f"idea-{attempted + 1:03d}"
    phase_state["attempted_slots"] = attempted + 1
    ideas[new_id] = new_idea_slot(new_id, int(phase_state["attempted_slots"]))
    add_active_idea(phase_state, new_id)
    return new_id


def next_intent_id(phase_state: dict[str, Any]) -> str:
    return f"intent-{len(phase_state.setdefault('intents', {})) + 1:03d}"


def next_batch_id(phase_state: dict[str, Any]) -> str:
    batches = phase_state.setdefault("batches", [])
    if not isinstance(batches, list):
        raise IdeationStateError("loop-state.json state.batches must be a list")
    return f"batch-{len(batches) + 1:03d}"


def refresh_batch_status(phase_state: dict[str, Any], batch_id: str | None) -> None:
    if not batch_id:
        return
    intents = phase_state.setdefault("intents", {})
    terminal = {"completed", "cancelled", "error"}
    for batch in phase_state.setdefault("batches", []):
        if isinstance(batch, dict) and batch.get("batch_id") == batch_id:
            intent_ids = batch.get("intent_ids") if isinstance(batch.get("intent_ids"), list) else []
            if intent_ids and all(str(intents.get(intent_id, {}).get("status") or "") in terminal for intent_id in intent_ids):
                batch["status"] = "completed"
                batch["completed_at"] = utc_now()
            return


def start_intent_batch(
    target_repo: Path,
    run_id: str,
    role: str,
    *,
    count: int | None = None,
    idea_ids: list[str] | None = None,
    agent_thread_id: str | None = None,
) -> dict[str, Any]:
    if role not in INTENT_ROLES:
        raise IdeationStateError(f"invalid intent role: {role}")
    cfg = current_config(target_repo, run_id)
    limit = max_subagents(cfg)
    requested_count = count
    batch_holder: dict[str, Any] = {}

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        pending = pending_intents(phase_state)
        if pending:
            raise IdeationStateError("subagent intents are already pending")
        if role == "generator":
            if idea_ids:
                if len(idea_ids) > limit:
                    raise IdeationStateError(f"batch size {len(idea_ids)} exceeds max_subagents {limit}")
                resolved_idea_ids = [allocate_idea_if_needed(phase_state, item) for item in idea_ids]
            else:
                if count is None or count <= 0:
                    raise IdeationStateError("generator batch requires --count > 0")
                if count > limit:
                    raise IdeationStateError(f"batch size {count} exceeds max_subagents {limit}")
                resolved_idea_ids = [allocate_new_idea(phase_state) for _ in range(count)]
        elif role == "critic":
            if not idea_ids:
                raise IdeationStateError("critic batch requires --idea-ids")
            if len(idea_ids) > limit:
                raise IdeationStateError(f"batch size {len(idea_ids)} exceeds max_subagents {limit}")
            resolved_idea_ids = list(idea_ids)
        elif role in {"selector", "schema_builder"}:
            role_count = requested_count if requested_count is not None else len(idea_ids or []) or 1
            if role_count <= 0:
                raise IdeationStateError(f"{role} batch requires --count > 0")
            if role_count > limit:
                raise IdeationStateError(f"batch size {role_count} exceeds max_subagents {limit}")
            resolved_idea_ids = list(idea_ids or [f"{role}-{index + 1:03d}" for index in range(role_count)])
        else:
            raise IdeationStateError(f"invalid intent role: {role}")
        batch_id = next_batch_id(phase_state)
        batch = {
            "batch_id": batch_id,
            "role": role,
            "status": "running",
            "concurrency_limit": limit,
            "intent_ids": [],
            "started_at": utc_now(),
            "completed_at": None,
        }
        created: list[dict[str, Any]] = []
        intents = phase_state.setdefault("intents", {})
        for resolved_idea_id in resolved_idea_ids:
            intent_id = next_intent_id(phase_state)
            result_path = pending_result_path(target_repo, run_id, intent_id)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.touch(exist_ok=False)
            intent = {
                "intent_id": intent_id,
                "batch_id": batch_id,
                "role": role,
                "idea_id": resolved_idea_id,
                "result_path": str(result_path),
                "status": "running",
                "agent_thread_id": agent_thread_id,
                "started_at": utc_now(),
                "completed_at": None,
                "reason": None,
                "error": None,
            }
            intents[intent_id] = intent
            pending[intent_id] = intent
            batch["intent_ids"].append(intent_id)
            created.append(deepcopy(intent))
        phase_state.setdefault("batches", []).append(batch)
        batch_holder.update({"batch": deepcopy(batch), "intents": created})
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "subagent_event", {"command": "ideation intent start-batch", "role": role, "count": count, "idea_ids": idea_ids}, mutator, subagent_id=None)
    sync_ideas_archive(target_repo, run_id, updated)
    return batch_holder


def start_intent(target_repo: Path, run_id: str, role: str, *, idea_id: str | None = None, agent_thread_id: str | None = None) -> dict[str, Any]:
    if role == "generator":
        if idea_id:
            return start_intent_batch(target_repo, run_id, role, idea_ids=[idea_id], agent_thread_id=agent_thread_id)["intents"][0]
        return start_intent_batch(target_repo, run_id, role, count=1, agent_thread_id=agent_thread_id)["intents"][0]
    if role == "critic":
        if not idea_id:
            state = ensure_active_ideation_state(target_repo, run_id)
            phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
            idea_id = resolve_idea_id(phase_state, None, "critic intent")
        return start_intent_batch(target_repo, run_id, role, idea_ids=[idea_id], agent_thread_id=agent_thread_id)["intents"][0]
    if role in {"selector", "schema_builder"}:
        return start_intent_batch(target_repo, run_id, role, count=1, agent_thread_id=agent_thread_id)["intents"][0]
    raise IdeationStateError(f"invalid intent role: {role}")


def resolve_pending_intent(phase_state: dict[str, Any], intent_id: str | None = None) -> dict[str, Any]:
    pending = pending_intents(phase_state)
    if intent_id:
        intent = pending.get(intent_id)
        if not isinstance(intent, dict):
            raise IdeationStateError(f"unknown pending intent_id: {intent_id}")
        return intent
    if len(pending) == 1:
        return next(iter(pending.values()))
    if not pending:
        raise IdeationStateError("no pending subagent intent")
    raise IdeationStateError("--intent-id is required when multiple intents are pending")


def clear_pending_intent_for_role(phase_state: dict[str, Any], role: str, idea_id: str | None = None, intent_id: str | None = None) -> None:
    pending_map = pending_intents(phase_state)
    if not pending_map:
        return
    pending = resolve_pending_intent(phase_state, intent_id)
    if pending.get("role") != role:
        raise IdeationStateError(f"pending intent role is {pending.get('role')}, not {role}")
    if idea_id and pending.get("idea_id") != idea_id:
        raise IdeationStateError("pending intent idea_id mismatch")
    resolved_intent_id = pending.get("intent_id")
    batch_id = pending.get("batch_id")
    if isinstance(resolved_intent_id, str):
        pending.update({"status": "completed", "completed_at": utc_now()})
        phase_state.setdefault("intents", {}).setdefault(resolved_intent_id, {}).update(pending)
        pending_map.pop(resolved_intent_id, None)
    refresh_batch_status(phase_state, batch_id if isinstance(batch_id, str) else None)


def complete_intent(target_repo: Path, run_id: str, payload: dict[str, Any], *, intent_id: str | None = None) -> dict[str, Any]:
    state = ensure_active_ideation_state(target_repo, run_id)
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    pending = resolve_pending_intent(phase_state, intent_id)
    if not payload:
        path_value = pending.get("result_path")
        if not isinstance(path_value, str) or not path_value:
            raise IdeationStateError("pending intent has no result_path; pass --json or --path")
        payload_path = Path(path_value)
        if not payload_path.exists() or not payload_path.read_text().strip():
            raise IdeationStateError(f"pending result_path is empty: {payload_path}")
        text = payload_path.read_text()
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                parsed = {"value": parsed}
            payload = parsed
        except json.JSONDecodeError:
            payload = {"text": text}
    role = str(pending.get("role") or "")
    if role == "generator":
        return record_draft(target_repo, run_id, payload, idea_id=pending.get("idea_id"), intent_id=pending.get("intent_id"))
    if role == "critic":
        return record_feedback(target_repo, run_id, payload, "critic_feedback", idea_id=pending.get("idea_id"), intent_id=pending.get("intent_id"))
    if role == "selector":
        return record_feedback(target_repo, run_id, payload, "selector_reports", idea_id=pending.get("idea_id"), intent_id=pending.get("intent_id"))
    if role == "schema_builder":
        return record_feedback(target_repo, run_id, payload, "schema_builder_reports", idea_id=pending.get("idea_id"), intent_id=pending.get("intent_id"))
    raise IdeationStateError(f"unknown pending intent role: {role}")


def cancel_intent(target_repo: Path, run_id: str, reason: str, *, intent_id: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        pending_map = pending_intents(phase_state)
        pending = resolve_pending_intent(phase_state, intent_id)
        pending["status"] = "cancelled"
        pending["reason"] = reason
        pending["completed_at"] = utc_now()
        resolved_intent_id = pending.get("intent_id")
        if isinstance(resolved_intent_id, str):
            phase_state.setdefault("intents", {}).setdefault(resolved_intent_id, {}).update(pending)
            pending_map.pop(resolved_intent_id, None)
        batch_id = pending.get("batch_id")
        refresh_batch_status(phase_state, batch_id if isinstance(batch_id, str) else None)
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "subagent_event", {"command": "ideation intent cancel", "reason": reason, "intent_id": intent_id}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def normalize_idea_payload(payload: dict[str, Any], idea_id: str, run_id: str) -> dict[str, Any]:
    idea = deepcopy(payload)
    idea.setdefault("id", idea_id)
    if idea["id"] != idea_id:
        raise IdeationStateError(f"idea id mismatch: expected {idea_id}, got {idea['id']}")
    if not any(has_substantive_value(idea.get(key)) for key in ("title", "hypothesis", "abstract", "Name", "Title", "Short Hypothesis")):
        raise IdeationStateError("idea draft must include at least a title, hypothesis, abstract, or upstream hypothesis field")
    idea.setdefault("source_run_id", run_id)
    return idea


def payload_ideas(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("idea"), dict):
        return [payload["idea"]]
    for key in ("ideas", "idea_batch", "final_ideas", "selected_ideas"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if any(has_substantive_value(payload.get(key)) for key in IDEA_OUTPUT_SCHEMA["required"]):
        return [payload]
    return []


def record_draft(target_repo: Path, run_id: str, payload: dict[str, Any], *, idea_id: str | None = None, intent_id: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = allocate_idea_if_needed(phase_state, idea_id)
        ideas = phase_state.setdefault("idea_states", {})
        idea = ideas.setdefault(resolved_id, {"id": resolved_id})
        draft_version = int(idea.get("draft_version") or 0) + 1
        if "text" in payload and len(payload) == 1:
            draft_ref = write_text_log(target_repo, run_id, "drafts", f"{resolved_id}-v{draft_version:02d}.md", str(payload["text"]))
            normalized = {"text": payload["text"]}
            compact = {}
        else:
            normalized = deepcopy(payload)
            compact_candidates = payload_ideas(payload)
            compact = compact_idea_payload(normalize_idea_payload(compact_candidates[0], resolved_id, run_id), resolved_id, run_id) if compact_candidates else {}
            draft_ref = write_payload_log(target_repo, run_id, "drafts", f"{resolved_id}-v{draft_version:02d}.json", normalized)
        idea_hash = data_hash(normalized)
        idea.update({
            "id": resolved_id,
            "source_run_id": run_id,
            "status": "drafted",
            "latest_draft": compact,
            "draft_version": draft_version,
            "idea_hash": idea_hash,
            "draft_ref": str(draft_ref),
            "updated_at": utc_now(),
        })
        idea.setdefault("drafts", []).append({"draft_version": draft_version, "idea_hash": idea_hash, "draft_ref": str(draft_ref)})
        phase_state.setdefault("artifacts", {}).setdefault("idea_batches", []).append(str(draft_ref))
        clear_pending_intent_for_role(phase_state, "generator", resolved_id, intent_id=intent_id)
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation intent complete", "role": "generator", "idea_id": idea_id}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def record_feedback(target_repo: Path, run_id: str, payload: dict[str, Any], artifact_key: str, *, idea_id: str | None = None, intent_id: str | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        resolved_id = str(idea_id or "batch")
        pending = resolve_pending_intent(phase_state, intent_id)
        role = str(pending.get("role") or artifact_key)
        subdir = "critics" if artifact_key == "critic_feedback" else "selectors" if artifact_key == "selector_reports" else "schema"
        index = len(phase_state.setdefault("artifacts", {}).setdefault(artifact_key, [])) + 1
        if "text" in payload and len(payload) == 1:
            ref = write_text_log(target_repo, run_id, subdir, f"{resolved_id}-{index:02d}.md", str(payload["text"]))
        else:
            ref = write_payload_log(target_repo, run_id, subdir, f"{resolved_id}-{index:02d}.json", payload)
        phase_state.setdefault("artifacts", {}).setdefault(artifact_key, []).append(str(ref))
        if artifact_key == "schema_builder_reports":
            phase_state.setdefault("artifacts", {})["final_schema"] = str(ref)
        clear_pending_intent_for_role(phase_state, role, idea_id, intent_id=intent_id)
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "subagent_event", {"command": "ideation intent complete", "role": artifact_key, "idea_id": idea_id}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated


def apply_finalized_idea(phase_state: dict[str, Any], idea: dict[str, Any], compact: dict[str, Any], rank: int) -> None:
    idea["latest_draft"] = compact
    idea["idea_hash"] = data_hash(compact)
    idea["status"] = "selected"
    idea["evaluation"] = "ACCEPTED"
    idea["score"] = compact.get("score") if isinstance(compact.get("score"), int) else 80
    idea["rank"] = rank
    idea["selected"] = True
    idea["researchable"] = True
    idea["updated_at"] = utc_now()
    remove_active_idea(phase_state, str(idea["id"]))
    phase_state["accepted_count"] = int(phase_state.get("accepted_count") or 0) + 1


def finalize_ready(target_repo: Path, run_id: str, *, idea_ids: list[str] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    contract = load_ideation_contract(target_repo, run_id)
    campaign_contract = run_research_contract(cfg)
    final_payload = payload or {}

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        ideas = phase_state.setdefault("idea_states", {})
        final_ideas = payload_ideas(final_payload)
        if not final_ideas and idea_ids:
            final_ideas = [
                ideas[item].get("latest_draft")
                for item in idea_ids
                if isinstance(ideas.get(item), dict) and isinstance(ideas[item].get("latest_draft"), dict)
            ]
        if not final_ideas:
            raise IdeationStateError("finalize-ready requires final idea schema via --json/--json-file or --idea-ids with schema drafts")
        selected: list[tuple[str, dict[str, Any]]] = []
        batch_keys: dict[tuple[Any, Any, Any], str] = {}
        for index, item in enumerate(final_ideas, start=1):
            idea_id = str(item.get("id") or f"idea-{index:03d}")
            compact = compact_idea_payload(normalize_idea_payload(item, idea_id, run_id), idea_id, run_id)
            validate_minimum_command(compact, contract)
            validate_idea_fits_campaign(compact, campaign_contract)
            dedup_key = (compact.get("family_key"), compact.get("unique_protocol"), compact.get("expected_metric"))
            if dedup_key in batch_keys:
                raise IdeationStateError(f"duplicate_idea_family:{idea_id}:{batch_keys[dedup_key]}")
            batch_keys[dedup_key] = idea_id
            selected.append((idea_id, compact))
        for rank, (idea_id, compact) in enumerate(selected, start=1):
            idea = ideas.setdefault(idea_id, new_idea_slot(idea_id, rank))
            apply_finalized_idea(phase_state, idea, compact, rank)
        final_ref = write_payload_log(target_repo, run_id, "final", "selected-ideas.json", {"ideas": [item for _, item in selected]})
        phase_state.setdefault("artifacts", {})["final_schema"] = str(final_ref)
        increment_iteration(phase_state)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation finalize-ready", "idea_ids": idea_ids}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    return updated

def completion_audit(state: dict[str, Any], config: dict[str, Any], status: str) -> dict[str, Any]:
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    candidates = researchable_candidates(state, config)
    return {
        "passed": True,
        "status": status,
        "prompt_to_artifact_checklist": [
            f"Attempted {phase_state.get('attempted_slots')} ideation slots",
            f"Recorded {len(terminal_ideas(state))} selected idea records",
            f"Identified {len(candidates)} researchable candidates",
        ],
        "verification_evidence": [
            f".ai-scientist/runs/{state.get('run_id')}/loop-state.json",
            f".ai-scientist/runs/{state.get('run_id')}/ideas.json",
            f".ai-scientist/runs/{state.get('run_id')}/journal.jsonl",
        ],
    }


def final_summary(state: dict[str, Any]) -> dict[str, Any]:
    attempted = [{"idea_id": idea.get("id"), "evaluation": idea.get("evaluation"), "score": idea.get("score")} for idea in terminal_ideas(state)]
    return {"attempted_ideas": attempted, "reason": "no researchable candidate was produced"}


def complete_ideation(target_repo: Path, run_id: str) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    validate_campaign_research_contract(cfg.get("research_contract"))

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        if pending_intents(phase_state):
            raise IdeationStateError("pending subagent intent blocks completion")
        candidates = researchable_candidates(state, cfg)
        if len(candidates) < int(phase_state.get("min_candidates_required") or 1):
            raise IdeationStateError("not enough researchable candidates")
        phase_state["handoff"] = {
            "status": "ready",
            "idea_batch": [idea["id"] for idea in candidates],
            "candidates": [
                {
                    "idea_id": idea["id"],
                    "evaluation": idea.get("evaluation"),
                    "score": idea.get("score"),
                    "idea_hash": idea.get("idea_hash"),
                }
                for idea in candidates
            ],
            "research_contract_hash": data_hash(cfg.get("research_contract")),
        }
        status = "COMPLETED"
        state["active"] = False
        state["phase_status"] = status
        state["run_outcome"] = status
        state["completed_at"] = utc_now()
        state["completion_audit"] = completion_audit(state, cfg, status)
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation complete"}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    append_journal_event(target_repo, run_id, "validation", details={"gate": "ideation_to_research", "exit_code": 0, "validator_exit_code": 0, "command": "ideation complete"})
    append_journal_event(target_repo, run_id, "handoff", details={"gate": "ideation_to_research", "approved": True, "exit_code": 0, "validator_exit_code": 0, "reason": "ideation handoff ready"})
    set_active_run(target_repo, run_id, "ideation", "completed")
    return updated


def exhaust_ideation(target_repo: Path, run_id: str) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)
    state = ensure_active_ideation_state(target_repo, run_id)
    if researchable_candidates(state, cfg):
        return complete_ideation(target_repo, run_id)

    def mutator(new_state: dict[str, Any]) -> None:
        phase_state = new_state.setdefault("state", {})
        if pending_intents(phase_state):
            raise IdeationStateError("pending subagent intent blocks exhaustion")
        new_state["active"] = False
        new_state["phase_status"] = "EXHAUSTED_NO_CANDIDATE"
        new_state["run_outcome"] = "EXHAUSTED_NO_CANDIDATE"
        new_state["completed_at"] = utc_now()
        phase_state["final_summary"] = final_summary(new_state)
        new_state["completion_audit"] = completion_audit(new_state, cfg, "EXHAUSTED_NO_CANDIDATE")
        update_cursor(new_state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation exhaust"}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    append_journal_event(target_repo, run_id, "handoff", details={"gate": "ideation_to_research", "approved": False, "exit_code": 1, "validator_exit_code": 1, "reason": "no researchable candidate"})
    set_active_run(target_repo, run_id, "ideation", "exhausted")
    return updated


def cancel_ideation(target_repo: Path, run_id: str, reason: str) -> dict[str, Any]:
    cfg = current_config(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        pending_map = pending_intents(phase_state)
        for pending in list(pending_map.values()):
            pending["status"] = "cancelled"
            pending["reason"] = reason
            pending["completed_at"] = utc_now()
            intent_id = pending.get("intent_id")
            if isinstance(intent_id, str):
                phase_state.setdefault("intents", {}).setdefault(intent_id, {}).update(pending)
            batch_id = pending.get("batch_id")
            refresh_batch_status(phase_state, batch_id if isinstance(batch_id, str) else None)
        pending_map.clear()
        state["active"] = False
        state["phase_status"] = "CANCELLED"
        state["run_outcome"] = "CANCELLED"
        state["cancellation_reason"] = reason
        state["completed_at"] = utc_now()
        update_cursor(state, cfg)

    updated = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "ideation cancel", "reason": reason}, mutator)
    sync_ideas_archive(target_repo, run_id, updated)
    set_active_run(target_repo, run_id, "ideation", "cancelled")
    return updated

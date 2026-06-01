#!/usr/bin/env python3
"""Install project-local Codex hooks for AI Scientist."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ai_scientist_codex.core.state import start_phase


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def hook_command(python: str, script: Path, target_repo: Path | None = None) -> str:
    parts = [python, str(script)]
    if target_repo is not None:
        parts.extend(["--target-repo", str(target_repo)])
    return " ".join(shlex.quote(part) for part in parts)


def hook_cli_command(target_repo: Path | None = None) -> str:
    parts = ["ai-scientist", "hooks", "stop-gate"]
    if target_repo is not None:
        parts.extend(["--target-repo", str(target_repo)])
    return " ".join(shlex.quote(part) for part in parts)


def default_stop_hook_script() -> Path:
    checkout_script = Path(__file__).resolve().parents[3] / "plugins" / "ai-scientist" / "scripts" / "ai_scientist_stop_hook.py"
    if checkout_script.exists():
        return checkout_script
    return Path(__file__).resolve().with_name("stop_gate.py")


def is_ai_scientist_command(command: str) -> bool:
    return "ai_scientist_stop_hook.py" in command or "ai-scientist hooks stop-gate" in command


def is_ai_scientist_hook_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = hook.get("command")
        if isinstance(command, str) and is_ai_scientist_command(command):
            return True
    return False


def install_hooks_json(project_root: Path, python: str, script: Path, *, command_style: str = "script") -> Path:
    hooks_path = project_root / ".codex" / "hooks.json"
    config = load_json_object(hooks_path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(".codex/hooks.json hooks must be an object")
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        stop_entries = []
    stop_entries = [entry for entry in stop_entries if not is_ai_scientist_hook_entry(entry)]
    stop_entries.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_cli_command() if command_style == "cli" else hook_command(python, script),
                    "timeout": 30,
                }
            ]
        }
    )
    hooks["Stop"] = stop_entries
    write_json(hooks_path, config)
    return hooks_path


def enable_hooks_feature(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return "[features]\nhooks = true\n"

    features_start: int | None = None
    features_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[features]":
            features_start = index
            continue
        if features_start is not None and index > features_start and stripped.startswith("[") and stripped.endswith("]"):
            features_end = index
            break

    if features_start is None:
        suffix = "" if content.endswith("\n") else "\n"
        return content + suffix + "\n[features]\nhooks = true\n"

    for index in range(features_start + 1, features_end):
        stripped = lines[index].strip()
        if stripped.startswith("hooks ") or stripped.startswith("hooks="):
            lines[index] = "hooks = true"
            return "\n".join(lines) + "\n"
        if stripped.startswith("codex_hooks ") or stripped.startswith("codex_hooks="):
            lines[index] = "hooks = true"
            return "\n".join(lines) + "\n"

    lines.insert(features_start + 1, "hooks = true")
    return "\n".join(lines) + "\n"


def install_config_toml(project_root: Path) -> Path:
    config_path = project_root / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = config_path.read_text() if config_path.exists() else ""
    config_path.write_text(enable_hooks_feature(content))
    return config_path


def command_is_installed(hooks_path: Path) -> bool:
    return bool(configured_hook_commands(hooks_path))


def configured_hook_commands(hooks_path: Path) -> list[str]:
    config = load_json_object(hooks_path)
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return []
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        return []
    commands: list[str] = []
    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            continue
        for hook in entry_hooks:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            if isinstance(command, str) and is_ai_scientist_command(command):
                commands.append(command)
    return commands


def config_enables_hooks(config_path: Path) -> bool:
    if not config_path.exists():
        return False
    return any(line.strip() == "hooks = true" for line in config_path.read_text().splitlines())


def validate_hook_command(command: str, expected_script: Path) -> list[str]:
    parts = shlex.split(command)
    if len(parts) >= 3 and parts[:3] == ["ai-scientist", "hooks", "stop-gate"]:
        if "--target-repo" in parts:
            raise RuntimeError("AI Scientist project-local Stop hook command must not embed --target-repo")
        return parts
    script_parts = [part for part in parts if part.endswith("ai_scientist_stop_hook.py")]
    if len(script_parts) != 1:
        raise RuntimeError(f"AI Scientist Stop hook command must include exactly one hook script path: {command}")
    script_path = Path(script_parts[0])
    if not script_path.exists():
        raise RuntimeError(f"AI Scientist Stop hook script is missing: {script_path}")
    if script_path.resolve() != expected_script.resolve():
        raise RuntimeError(
            "AI Scientist Stop hook points to a different plugin checkout: "
            f"{script_path.resolve()} != {expected_script.resolve()}"
        )
    if "--target-repo" in parts:
        raise RuntimeError("AI Scientist project-local Stop hook command must not embed --target-repo")
    return parts


def run_hook_smoke(command: str, script: Path) -> None:
    parts = validate_hook_command(command, script)
    with tempfile.TemporaryDirectory(prefix="ai-scientist-hook-check-") as tmp:
        target = Path(tmp)
        start_phase(
            target,
            "check-run",
            "ideation",
            {
                "num_ideas_required": 1,
                "num_reflections_required": 1,
                "current_idea_index": 1,
                "current_reflection_round": 1,
                "finalized_count": 0,
                "skipped_count": 0,
                "s2_query_count": 0,
                "idea_states": {
                    "idea-001": {"status": "reflecting", "reflection_count": 0}
                },
            },
        )
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(target)})
        proc = subprocess.run(
            parts,
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Stop hook smoke failed: {proc.stderr.strip()}")
        try:
            output = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Stop hook did not emit JSON: {proc.stdout!r}") from exc
        if output.get("decision") != "block":
            raise RuntimeError(f"Stop hook smoke expected decision=block, got {output}")


def check_install(project_root: Path, python: str, script: Path) -> None:  # noqa: ARG001 - python is kept for CLI compatibility.
    hooks_path = project_root / ".codex" / "hooks.json"
    config_path = project_root / ".codex" / "config.toml"
    commands = configured_hook_commands(hooks_path)
    if not commands:
        raise RuntimeError(f"AI Scientist Stop hook is not installed in {hooks_path}")
    if len(commands) != 1:
        raise RuntimeError(f"Expected exactly one AI Scientist Stop hook command in {hooks_path}, found {len(commands)}")
    if not config_enables_hooks(config_path):
        raise RuntimeError(f"Codex hooks feature is not enabled in {config_path}")
    run_hook_smoke(commands[0], script)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--python", default=sys.executable, help="Python interpreter used by Codex hook command.")
    parser.add_argument("--check", action="store_true", help="Verify existing hook setup and run a local smoke test.")
    default_style = "script" if Path(sys.argv[0]).name == "install_codex_hooks.py" else "cli"
    parser.add_argument("--command-style", choices=["cli", "script"], default=default_style, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    script = default_stop_hook_script()

    if args.check:
        check_install(project_root, args.python, script)
        print(json.dumps({"ok": True, "checked": str(project_root)}, indent=2))
        return 0

    hooks_path = install_hooks_json(project_root, args.python, script, command_style=args.command_style)
    config_path = install_config_toml(project_root)
    check_install(project_root, args.python, script)
    print(json.dumps({"ok": True, "hooks_path": str(hooks_path), "config_path": str(config_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

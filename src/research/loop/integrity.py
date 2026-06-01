from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .journal import write_json

IGNORE_DIRS = {".ai-scientist", ".git", "__pycache__"}


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORE_DIRS for part in rel_parts):
            continue
        if path.is_symlink():
            result[str(path.relative_to(root))] = {"type": "symlink", "target": str(path.readlink())}
        elif path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = {"type": "file", "size": stat.st_size, "sha256": _hash(path)}
    return result


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            changes.append({"path": path, "operation": "created", "after": after[path]})
        elif path not in after:
            changes.append({"path": path, "operation": "deleted", "before": before[path]})
        elif before[path] != after[path]:
            changes.append({"path": path, "operation": "modified", "before": before[path], "after": after[path]})
    return changes


def write_mutation_check(path: Path, changes: list[dict[str, Any]], command: list[str] | str, return_code: int) -> bool:
    passed = not changes
    write_json(path, {"passed": passed, "changed_paths": changes, "command": command, "return_code": return_code, "block_reason": None if passed else "runtime mutation outside .ai-scientist detected"})
    return passed

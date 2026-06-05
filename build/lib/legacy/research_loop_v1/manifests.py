from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .journal import write_json

KNOWN_ARTIFACTS = ["metrics.json", "split_integrity.json", "leakage_check.json", "result_summary.json", "mode_deliverables.json"]


class ManifestError(ValueError):
    pass


def parse_manifest(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ManifestError(f"agent output is not JSON: {exc}") from exc
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ManifestError("agent manifest must be an object")
    return data


def _safe_destination(workspace: Path, rel: str) -> Path:
    if not rel or os.path.isabs(rel):
        raise ManifestError(f"unsafe manifest path: {rel!r}")
    raw = Path(rel)
    if any(part in {"..", ""} for part in raw.parts):
        raise ManifestError(f"unsafe manifest path: {rel!r}")
    dest = (workspace / raw).resolve()
    root = workspace.resolve()
    if dest != root and root not in dest.parents:
        raise ManifestError(f"manifest path escapes workspace: {rel}")
    return dest


def validate_manifest(manifest: dict[str, Any], workspace: Path, metric_key: str, metric_direction: str) -> dict[str, Any]:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError("manifest.files must be a non-empty list")
    seen: set[Path] = set()
    normalized: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ManifestError("each manifest file needs a string path")
        dest = _safe_destination(workspace, item["path"])
        if dest in seen:
            raise ManifestError(f"duplicate manifest path after normalization: {item['path']}")
        seen.add(dest)
        content = item.get("content")
        if not isinstance(content, str):
            raise ManifestError(f"manifest file content must be string: {item['path']}")
        normalized.append({"path": item["path"], "resolved_path": str(dest), "content": content, "executable": bool(item.get("executable"))})
    command = manifest.get("command")
    if not (isinstance(command, list) and command and all(isinstance(part, str) for part in command)):
        raise ManifestError("manifest.command must be a non-empty string list")
    expected = manifest.get("expected_metrics", {})
    if expected.get("metric_key") != metric_key or expected.get("metric_direction") != metric_direction:
        raise ManifestError("manifest expected_metrics must match declared metric contract")
    return {**manifest, "files": normalized, "command": command}


def materialize_manifest(manifest: dict[str, Any], workspace: Path, validation_path: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    accepted = []
    for item in manifest["files"]:
        dest = Path(item["resolved_path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item["content"])
        if item.get("executable"):
            dest.chmod(dest.stat().st_mode | 0o111)
        accepted.append({"path": item["path"], "resolved_path": str(dest)})
    write_json(validation_path, {"accepted": True, "files": accepted, "reason": "manifest passed path and metric validation"})


def copy_workspace_artifacts(workspace: Path, node_dir: Path) -> None:
    for name in KNOWN_ARTIFACTS:
        src = workspace / name
        if src.exists() and src.is_file():
            (node_dir / name).write_text(src.read_text())

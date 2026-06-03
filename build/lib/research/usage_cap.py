"""Codex account usage-cap helpers for AI Scientist research loops."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any


DEFAULT_USAGE_CAP = {
    "enabled": True,
    "warning_threshold_percent": 85,
    "cap_threshold_percent": 95,
    "poll_interval_seconds": 600,
    "limit_id": "codex",
    "source": "codex app-server account/rateLimits/read",
    "no_limit_host_cap": False,
}


class UsageCapError(RuntimeError):
    """Raised when Codex usage cannot be read or normalized."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def merge_usage_cap_config(research_config: dict[str, Any] | None, *, no_limit_host_cap: bool | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_USAGE_CAP)
    override = {}
    if isinstance(research_config, dict):
        override = research_config.get("usage_cap") if isinstance(research_config.get("usage_cap"), dict) else {}
    config.update(override)
    if no_limit_host_cap is not None:
        config["no_limit_host_cap"] = bool(no_limit_host_cap)
    config["enabled"] = bool(config.get("enabled", True))
    config["no_limit_host_cap"] = bool(config.get("no_limit_host_cap", False))
    config["warning_threshold_percent"] = float(config.get("warning_threshold_percent", 85))
    config["cap_threshold_percent"] = float(config.get("cap_threshold_percent", 95))
    config["poll_interval_seconds"] = int(config.get("poll_interval_seconds", 600))
    config["limit_id"] = str(config.get("limit_id") or "codex")
    config["source"] = str(config.get("source") or DEFAULT_USAGE_CAP["source"])
    return config


def is_snapshot_fresh(usage_state: dict[str, Any] | None, poll_interval_seconds: int, *, now: datetime | None = None) -> bool:
    if not isinstance(usage_state, dict):
        return False
    snapshot = usage_state.get("snapshot")
    if not isinstance(snapshot, dict):
        return False
    checked_at = snapshot.get("checked_at")
    if not isinstance(checked_at, str):
        return False
    try:
        checked = parse_utc(checked_at)
    except ValueError:
        return False
    current = now or datetime.now(timezone.utc)
    return (current - checked).total_seconds() < poll_interval_seconds


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError as exc:
            raise UsageCapError(f"invalid numeric rate-limit value: {value}") from exc
    return None


def _first_mapping(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _normalize_window(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    used_percent = _number(value.get("usedPercent", value.get("used_percent")))
    window_duration = _number(value.get("windowDurationMins", value.get("window_duration_mins")))
    resets_at = value.get("resetsAt", value.get("resets_at"))
    normalized: dict[str, Any] = {}
    if used_percent is not None:
        normalized["usedPercent"] = used_percent
    if window_duration is not None:
        normalized["windowDurationMins"] = window_duration
    if isinstance(resets_at, str) and resets_at:
        normalized["resetsAt"] = resets_at
    for key in ("limit", "remaining", "used", "window"):
        if key in value:
            normalized[key] = value[key]
    return normalized or None


def _unwrap_result(result: Any) -> Any:
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        for item in result["content"]:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return result
    return result


def _lookup_limit(payload: Any, limit_id: str) -> dict[str, Any]:
    payload = _unwrap_result(payload)
    if isinstance(payload, dict) and "result" in payload:
        payload = _unwrap_result(payload["result"])
    if not isinstance(payload, dict):
        raise UsageCapError("rateLimits response result must be an object")

    by_id = payload.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        entry = by_id.get(limit_id)
        if isinstance(entry, dict):
            return {"limit_id": limit_id, **entry}

    for key in ("rateLimits", "limits"):
        limits = payload.get(key)
        if isinstance(limits, list):
            for entry in limits:
                if isinstance(entry, dict) and str(entry.get("limit_id", entry.get("limitId", entry.get("id", "")))) == limit_id:
                    return entry

    current_id = payload.get("limit_id", payload.get("limitId", payload.get("id")))
    if current_id is None or str(current_id) == limit_id:
        return payload
    raise UsageCapError(f"rate limit id not found: {limit_id}")


def normalize_rate_limit_response(response: dict[str, Any], *, limit_id: str = "codex") -> dict[str, Any]:
    limit = _lookup_limit(response, limit_id)
    normalized_limit_id = str(limit.get("limit_id", limit.get("limitId", limit.get("id", limit_id))))
    primary = _normalize_window(_first_mapping(limit.get("primary"), limit.get("primaryWindow"), limit.get("primary_window")))
    secondary = _normalize_window(_first_mapping(limit.get("secondary"), limit.get("secondaryWindow"), limit.get("secondary_window")))
    if primary is None and secondary is None:
        primary = _normalize_window(limit)
    used_values = [
        window["usedPercent"]
        for window in (primary, secondary)
        if isinstance(window, dict) and isinstance(window.get("usedPercent"), (int, float))
    ]
    effective = max(used_values) if used_values else None
    if effective is None:
        raise UsageCapError(f"rate limit {normalized_limit_id} has no usedPercent")
    snapshot = {
        "limit_id": normalized_limit_id,
        "primary": primary,
        "secondary": secondary,
        "effective_used_percent": effective,
        "planType": limit.get("planType", limit.get("plan_type")),
        "rateLimitReachedType": limit.get("rateLimitReachedType", limit.get("rate_limit_reached_type")),
        "checked_at": utc_now(),
    }
    return {key: value for key, value in snapshot.items() if value is not None}


def _read_stdout(stdout: Any, out_queue: queue.Queue[str | None]) -> None:
    try:
        while True:
            line = stdout.readline()
            if line == "":
                out_queue.put(None)
                return
            out_queue.put(line)
    except Exception as exc:  # pragma: no cover - defensive bridge for subprocess pipes.
        out_queue.put(json.dumps({"jsonrpc": "2.0", "error": {"message": str(exc)}}) + "\n")


def _send_message(stdin: Any, payload: dict[str, Any]) -> None:
    stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stdin.flush()


def read_codex_rate_limits(*, codex_cmd: str = "codex", timeout_seconds: float = 10.0, limit_id: str = "codex") -> dict[str, Any]:
    proc = subprocess.Popen(
        [codex_cmd, "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.stdin is None or proc.stdout is None:
        raise UsageCapError("failed to open codex app-server stdio pipes")
    out_queue: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_read_stdout, args=(proc.stdout, out_queue), daemon=True)
    reader.start()
    try:
        _send_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "ai-scientist", "version": "1"}, "capabilities": {}},
            },
        )
        _send_message(proc.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _send_message(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}})
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                line = out_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise UsageCapError(f"malformed codex app-server response: {exc}") from exc
            if not isinstance(message, dict):
                raise UsageCapError("codex app-server response must be an object")
            if message.get("id") != 2:
                continue
            if "error" in message:
                raise UsageCapError(f"codex rateLimits error: {message['error']}")
            return normalize_rate_limit_response(message, limit_id=limit_id)
        raise UsageCapError("timed out waiting for account/rateLimits/read response")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

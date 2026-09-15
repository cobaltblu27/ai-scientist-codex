"""Dashboard-owned research sessions.

The Start-research modal posts a contract, a set of ideas and free-text
instructions. The server then launches a Claude Code session through the Claude
Agent SDK and keeps the subprocess: the browser can push follow-up messages,
interrupt the current turn, or stop the session. Records live under
`.ai-scientist/sessions/<session-id>/` (docs/SCHEMA.md section 3.12) so the
scanner and a later dashboard process can still show them.

Threading: every session runs its own daemon thread with its own asyncio loop.
Handler threads never touch the SDK client directly; they submit coroutines
with `asyncio.run_coroutine_threadsafe` and cancel the main task to stop.

Backends: only Claude is implemented. TODO(codex): a `CodexBackend` driving
`codex exec --json` (or the Codex app-server) behind the same `SessionBackend`
protocol.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncContextManager, Protocol

from core.message_box import MAX_PROMPT_CHARS
from core.plugin import plugin_root
from core.state import ai_root, append_jsonl, atomic_write_json, pid_is_running, utc_now

DIR_NAME = "sessions"
LIVE_STATUSES = {"starting", "running", "idle"}
TERMINAL_STATUSES = {"stopped", "failed", "detached"}
EVENT_TEXT_CHARS = 4_000
# System messages that only add noise to the console: per-hook lifecycle rows and thinking-token counters.
NOISY_SYSTEM_SUBTYPES = {"hook_started", "hook_response", "thinking_tokens"}
NOISY_MESSAGE_TYPES = {"StreamEvent", "TaskProgressMessage"}
SEND_TIMEOUT_SEC = 10.0
STOP_TIMEOUT_SEC = 15.0


class SessionError(ValueError):
    """A request the manager refuses; `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --- backend protocol --------------------------------------------------------


@dataclass
class LaunchSpec:
    session_id: str
    claude_session_id: str
    run_id: str
    cwd: Path
    contract_path: str
    idea_batch: str
    idea_ids: list[str]
    prompt: str
    plugin_dir: Path = field(default_factory=plugin_root)


class SessionClient(Protocol):
    async def query(self, prompt: str) -> None: ...

    def receive_messages(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...


class SessionBackend(Protocol):
    name: str

    def unavailable_reason(self) -> str | None:
        """Why launching is impossible right now (install hint), or None."""

    def open(self, spec: LaunchSpec) -> AsyncContextManager[SessionClient]:
        """An async context manager yielding a connected client."""

    def to_event(self, message: Any) -> dict[str, Any] | None:
        """Translate one backend message into an events.jsonl row (without `ts`), or None to drop it."""


def _clip(text: Any, limit: int = EVENT_TEXT_CHARS) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ClaudeSdkBackend:
    """Claude Agent SDK backend. Imports the SDK lazily so the dashboard runs without it."""

    name = "claude"

    def __init__(self, *, permission_mode: str = "bypassPermissions", model: str | None = None):
        self.permission_mode = permission_mode
        self.model = model

    def unavailable_reason(self) -> str | None:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as exc:
            return f"claude-agent-sdk is not installed ({exc}); run `uv sync --extra dashboard`"
        return None

    def open(self, spec: LaunchSpec) -> AsyncContextManager[SessionClient]:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        options = ClaudeAgentOptions(
            cwd=str(spec.cwd),
            session_id=spec.claude_session_id,
            plugins=[{"type": "local", "path": str(spec.plugin_dir)}],
            setting_sources=["user", "project"],
            permission_mode=self.permission_mode,  # type: ignore[arg-type]
            system_prompt={"type": "preset", "preset": "claude_code"},
            model=self.model,
        )
        return ClaudeSDKClient(options=options)

    def to_event(self, message: Any) -> dict[str, Any] | None:
        from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, StreamEvent, SystemMessage, TextBlock, ToolUseBlock, UserMessage

        if isinstance(message, RateLimitEvent):
            windows = rate_limit_windows(message.rate_limit_info)
            return {"type": "system", "subtype": "rate_limit", "rate_limits": windows, "text": "; ".join(describe_rate_limit(w) for w in windows)}
        if isinstance(message, SystemMessage):
            if message.subtype in NOISY_SYSTEM_SUBTYPES:
                return None
            row: dict[str, Any] = {"type": "system", "subtype": message.subtype}
            data = message.data if isinstance(message.data, dict) else {}
            if message.subtype == "init":
                row["session_id"] = data.get("session_id")
                row["text"] = _clip(f"model {data.get('model')}; skills {', '.join(map(str, data.get('skills') or []))}")
            else:
                row["text"] = _clip(json.dumps({k: v for k, v in data.items() if k not in {"session_id", "uuid"}}, default=str))
            return row
        if isinstance(message, AssistantMessage):
            texts, tools = [], []
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tools.append(block.name)
            if not texts and not tools:
                return None
            row = {"type": "assistant", "text": _clip("\n".join(texts))}
            if tools:
                row["tool"] = ", ".join(tools)
            if message.parent_tool_use_id:
                row["subtype"] = "subagent"
            return row
        if isinstance(message, ResultMessage):
            return {
                "type": "result",
                "subtype": message.subtype,
                "text": _clip(message.result),
                "session_id": message.session_id,
                "num_turns": message.num_turns,
                "is_error": bool(message.is_error),
            }
        if isinstance(message, (UserMessage, StreamEvent)) or message.__class__.__name__ in NOISY_MESSAGE_TYPES:
            return None  # dashboard sends are logged by the manager; tool results and counters are noise
        return {"type": "system", "subtype": message.__class__.__name__}


def rate_limit_window(status: Any, kind: Any, utilization: Any, resets_at: Any) -> dict[str, Any]:
    """One subscription rate-limit window as stored in `session.json` `rate_limits` (docs/SCHEMA.md 3.12)."""
    return {
        "type": kind if isinstance(kind, str) and kind else "unknown",
        "status": status if isinstance(status, str) else "unknown",
        "utilization": float(utilization) if isinstance(utilization, (int, float)) else None,
        "resets_at": int(resets_at) if isinstance(resets_at, (int, float)) else None,
    }


def rate_limit_windows(info: Any) -> list[dict[str, Any]]:
    """Every window in one CLI `rate_limit_event`.

    The CLI reports the binding window at the top level (`status`, `rateLimitType`, `resetsAt`, rarely
    `utilization`) and the per-window utilization under `unifiedWindows`, which the SDK leaves in `raw`.
    The top-level status only applies to its own window; the others are `allowed` unless they say otherwise.
    """
    raw = info.raw if isinstance(getattr(info, "raw", None), dict) else {}
    binding = rate_limit_window(info.status, info.rate_limit_type, info.utilization, info.resets_at)
    unified = raw.get("unifiedWindows")
    if not isinstance(unified, dict):
        return [binding]
    windows = []
    for kind, data in unified.items():
        if not isinstance(kind, str) or not isinstance(data, dict):
            continue
        status = binding["status"] if kind == binding["type"] else str(data.get("status") or "allowed")
        windows.append(rate_limit_window(status, kind, data.get("utilization"), data.get("resetsAt")))
    if binding["type"] not in {w["type"] for w in windows}:
        windows.append(binding)
    return windows


def describe_rate_limit(window: dict[str, Any]) -> str:
    used = window.get("utilization")
    pct = f"{round(used * 100)}%" if isinstance(used, float) else "?"
    resets = window.get("resets_at")
    when = datetime.fromtimestamp(resets, timezone.utc).strftime("%H:%MZ") if isinstance(resets, int) else "?"
    return f"{window['type']} window {window['status']}: {pct} used, resets {when}"


# --- one live session ---------------------------------------------------------


def sessions_dir(target_repo: Path) -> Path:
    return ai_root(target_repo) / DIR_NAME


def session_dir(target_repo: Path, session_id: str) -> Path:
    return sessions_dir(target_repo) / session_id


def _new_session_id(now: str) -> str:
    compact = now.replace("-", "").replace(":", "")
    return f"ses-{compact}-{secrets.token_hex(2)}"


def build_launch_prompt(spec: LaunchSpec) -> str:
    ideas = ", ".join(spec.idea_ids)
    lines = [
        f"/goal Complete a full ai-scientist research campaign for run {spec.run_id}: invoke the ai-scientist:research-loop skill "
        "and continue until it reaches one of its terminal outcomes with completion audit and handoff evidence.",
        f"Run id: {spec.run_id}. Target repository: {spec.cwd}.",
        f"Research contract: {spec.contract_path}. Idea batch: {spec.idea_batch} (ideas: {ideas}).",
    ]
    if spec.prompt.strip():
        lines += ["Additional instructions from the user:", spec.prompt.strip()]
    return "\n".join(lines)


class LiveSession:
    def __init__(self, target_repo: Path, backend: SessionBackend, spec: LaunchSpec, record: dict[str, Any]):
        self.target_repo = target_repo
        self.backend = backend
        self.spec = spec
        self.record = record
        self.prompt = build_launch_prompt(spec)
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._client: SessionClient | None = None
        self._started = threading.Event()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"session-{spec.session_id}", daemon=True)

    # -- files
    @property
    def dir(self) -> Path:
        return session_dir(self.target_repo, self.spec.session_id)

    def _save(self) -> None:
        self.record["updated_at"] = utc_now()
        atomic_write_json(self.dir / "session.json", self.record)

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self.record.update(fields)
            self._save()

    def append_event(self, row: dict[str, Any]) -> dict[str, Any]:
        event = {"ts": utc_now(), **row}
        with self._lock:
            append_jsonl(self.dir / "events.jsonl", event)
        return event

    # -- lifecycle
    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as exc:  # noqa: BLE001 - a dead thread must leave a readable record
            self._finish("failed", f"{exc.__class__.__name__}: {exc}")
        finally:
            self._started.set()
            self._done.set()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        try:
            async with self.backend.open(self.spec) as client:
                self._client = client
                self._started.set()
                await client.query(self.prompt)
                self.append_event({"type": "user", "origin": "launch", "text": self.prompt})
                async for message in client.receive_messages():
                    self._on_message(message)
            self._finish("stopped", None)
        except asyncio.CancelledError:
            self._finish("stopped", None)
        except Exception as exc:  # noqa: BLE001
            self._finish("failed", f"{exc.__class__.__name__}: {exc}")

    def _on_message(self, message: Any) -> None:
        row = self.backend.to_event(message)
        if not isinstance(row, dict):
            return
        self.append_event(row)
        fields: dict[str, Any] = {}
        if row.get("type") == "system" and row.get("subtype") == "init":
            fields["status"] = "running"
            if isinstance(row.get("session_id"), str):
                fields["claude_session_id"] = row["session_id"]
        elif row.get("type") == "system" and row.get("subtype") == "rate_limit" and isinstance(row.get("rate_limits"), list):
            with self._lock:
                limits = dict(self.record.get("rate_limits") or {})
            for window in row["rate_limits"]:
                if isinstance(window, dict) and isinstance(window.get("type"), str):
                    limits[window["type"]] = window
            fields["rate_limits"] = limits
        elif row.get("type") == "result":
            fields["status"] = "idle"
            if isinstance(row.get("num_turns"), int):
                fields["num_turns"] = int(self.record.get("num_turns") or 0) + row["num_turns"]  # cumulative over the session
            if isinstance(row.get("session_id"), str):
                fields["claude_session_id"] = row["session_id"]
            fields["error"] = row.get("text") if row.get("is_error") else None
        if fields:
            self._update(**fields)

    def _finish(self, status: str, error: str | None) -> None:
        with self._lock:
            if self.record.get("status") in TERMINAL_STATUSES:
                return
            self.record["status"] = status
            if error:
                self.record["error"] = error
            self._save()
        self.append_event({"type": "dashboard", "subtype": status, "text": error})

    # -- actions from handler threads
    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and self.record.get("status") in LIVE_STATUSES

    def send(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise SessionError("text is required")
        if len(text) > MAX_PROMPT_CHARS:
            raise SessionError(f"text longer than {MAX_PROMPT_CHARS} characters")
        self._started.wait(SEND_TIMEOUT_SEC)
        if not self.alive or self._client is None or self._loop is None:
            raise SessionError(f"session {self.spec.session_id} is not live", 409)
        # Mark the turn live before the message leaves, so a fast result cannot be overwritten by "running".
        self._update(status="running")
        event = self.append_event({"type": "user", "origin": "dashboard", "text": text})
        future = asyncio.run_coroutine_threadsafe(self._client.query(text), self._loop)
        try:
            future.result(SEND_TIMEOUT_SEC)
        except Exception as exc:  # noqa: BLE001
            self.append_event({"type": "dashboard", "subtype": "send-failed", "text": f"{exc.__class__.__name__}: {exc}"})
            raise SessionError(f"could not deliver message: {exc.__class__.__name__}: {exc}", 502) from exc
        return event

    def interrupt(self) -> None:
        self._started.wait(SEND_TIMEOUT_SEC)
        if not self.alive or self._client is None or self._loop is None:
            raise SessionError(f"session {self.spec.session_id} is not live", 409)
        self.append_event({"type": "dashboard", "subtype": "interrupt"})
        future = asyncio.run_coroutine_threadsafe(self._client.interrupt(), self._loop)
        future.add_done_callback(self._interrupt_done)

    def _interrupt_done(self, future: Any) -> None:
        exc = future.exception()
        if exc is not None:
            self.append_event({"type": "dashboard", "subtype": "interrupt-failed", "text": f"{exc.__class__.__name__}: {exc}"})

    def stop(self, timeout: float = STOP_TIMEOUT_SEC) -> None:
        if self._thread.is_alive() and self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.join(timeout)
        self._finish("stopped", None if not self._thread.is_alive() else "stop timed out; subprocess may linger")


# --- manager -----------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _safe_segment(value: str) -> bool:
    return bool(value) and "/" not in value and value not in {".", ".."}


def _idea_entries(root: Path, idea_ids: list[str]) -> list[dict[str, Any]]:
    """Selected entries from every ideation run's ideas.json, paths rewritten to `.ai-scientist/runs/<run>/...`."""
    wanted = list(dict.fromkeys(idea_ids))
    found: dict[str, dict[str, Any]] = {}
    try:
        run_dirs = sorted(p for p in (root / "runs").iterdir() if p.is_dir())
    except OSError:
        run_dirs = []
    for run in run_dirs:
        if (run / "loop-state.json").is_file():
            continue
        data = _read_json(run / "ideas.json")
        ideas = data.get("ideas") if isinstance(data, dict) else None
        if not isinstance(ideas, list):
            continue
        for idea in ideas:
            if not isinstance(idea, dict) or not isinstance(idea.get("id"), str) or idea["id"] not in wanted or idea["id"] in found:
                continue
            entry = dict(idea)
            entry["source_run_id"] = run.name
            for key in ("idea_file", "pilot_report"):
                value = entry.get(key)
                if isinstance(value, str) and value and not value.startswith(".ai-scientist/") and not value.startswith("/"):
                    entry[key] = f".ai-scientist/runs/{run.name}/{value}"
            found[idea["id"]] = entry
    missing = [i for i in wanted if i not in found]
    if missing:
        raise SessionError(f"unknown idea ids: {', '.join(missing)}")
    return [found[i] for i in wanted]


class SessionManager:
    def __init__(self, target_repo: Path, backend: SessionBackend | None = None):
        self.target_repo = target_repo.resolve()
        self.backend: SessionBackend = backend or ClaudeSdkBackend()
        self._live: dict[str, LiveSession] = {}
        self._lock = threading.Lock()
        self.reconcile()

    # -- records on disk
    def records(self) -> list[dict[str, Any]]:
        """Every readable session.json, newest first."""
        out = []
        try:
            dirs = [p for p in sessions_dir(self.target_repo).iterdir() if p.is_dir()]
        except OSError:
            return []
        for d in dirs:
            data = _read_json(d / "session.json")
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                out.append(data)
        out.sort(key=lambda r: (str(r.get("created_at") or ""), r["id"]), reverse=True)
        return out

    def reconcile(self) -> list[str]:
        """Mark records that claim to be live but whose owning process is gone as `detached`."""
        detached = []
        for record in self.records():
            if record.get("status") not in LIVE_STATUSES or record["id"] in self._live:
                continue
            pid = record.get("owner_pid")
            if isinstance(pid, int) and pid != os.getpid() and pid_is_running(pid):
                continue
            record["status"] = "detached"
            record["updated_at"] = utc_now()
            atomic_write_json(session_dir(self.target_repo, record["id"]) / "session.json", record)
            append_jsonl(session_dir(self.target_repo, record["id"]) / "events.jsonl", {"ts": record["updated_at"], "type": "dashboard", "subtype": "detached"})
            detached.append(record["id"])
        return detached

    def get(self, session_id: str) -> LiveSession | None:
        return self._live.get(session_id)

    # -- actions
    def launch(self, contract_id: str, idea_ids: list[str], prompt: str, run_id: str | None = None) -> dict[str, Any]:
        reason = self.backend.unavailable_reason()
        if reason:
            raise SessionError(reason, 503)
        root = ai_root(self.target_repo)
        contract_id = (contract_id or "").strip()
        if not _safe_segment(contract_id):
            raise SessionError("contract_id is required")
        contract_rel = f".ai-scientist/contracts/{contract_id}/research-contract.json"
        contract = _read_json(self.target_repo / contract_rel)
        if not isinstance(contract, dict) or not isinstance(contract.get("research_contract"), dict):
            raise SessionError(f"unknown or invalid contract: {contract_id}")
        if not isinstance(idea_ids, list) or not idea_ids or not all(isinstance(i, str) and i for i in idea_ids):
            raise SessionError("idea_ids must be a non-empty list of idea ids")
        prompt = prompt or ""
        if not isinstance(prompt, str):
            raise SessionError("prompt must be a string")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise SessionError(f"prompt longer than {MAX_PROMPT_CHARS} characters")
        now = utc_now()
        run_id = (run_id or "").strip() or f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}-research-{contract_id}"
        if not _safe_segment(run_id):
            raise SessionError(f"invalid run id: {run_id!r}")
        if (root / "runs" / run_id).exists():
            raise SessionError(f"run {run_id} already exists", 409)
        with self._lock:
            for live in self._live.values():
                if live.alive and live.record.get("run_id") == run_id:
                    raise SessionError(f"run {run_id} already has a live session {live.spec.session_id}", 409)
            ideas = _idea_entries(root, idea_ids)
            session_id = _new_session_id(now)
            while session_dir(self.target_repo, session_id).exists():
                session_id = _new_session_id(now)
            idea_batch = f".ai-scientist/{DIR_NAME}/{session_id}/ideas.json"
            spec = LaunchSpec(
                session_id=session_id,
                claude_session_id=str(uuid.uuid4()),
                run_id=run_id,
                cwd=self.target_repo,
                contract_path=contract_rel,
                idea_batch=idea_batch,
                idea_ids=[i["id"] for i in ideas],
                prompt=prompt,
            )
            record = {
                "id": session_id,
                "backend": self.backend.name,
                "status": "starting",
                "created_at": now,
                "updated_at": now,
                "run_id": run_id,
                "contract_path": contract_rel,
                "idea_batch": idea_batch,
                "prompt": prompt,
                "cwd": str(self.target_repo),
                "owner_pid": os.getpid(),
                "claude_session_id": spec.claude_session_id,
                "num_turns": 0,
                "rate_limits": {},
                "error": None,
            }
            atomic_write_json(session_dir(self.target_repo, session_id) / "ideas.json", {"session_id": session_id, "ideas": ideas})
            atomic_write_json(session_dir(self.target_repo, session_id) / "session.json", record)
            live = LiveSession(self.target_repo, self.backend, spec, record)
            self._live[session_id] = live
        live.start()
        return dict(record)

    def _require(self, session_id: str) -> LiveSession:
        live = self._live.get(session_id)
        if live is None:
            if session_dir(self.target_repo, session_id).is_dir() if _safe_segment(session_id) else False:
                raise SessionError(f"session {session_id} is not owned by this dashboard process", 409)
            raise SessionError(f"unknown session: {session_id}", 404)
        return live

    def send(self, session_id: str, text: str) -> dict[str, Any]:
        return self._require(session_id).send(text)

    def interrupt(self, session_id: str) -> dict[str, Any]:
        live = self._require(session_id)
        live.interrupt()
        return dict(live.record)

    def stop(self, session_id: str) -> dict[str, Any]:
        live = self._require(session_id)
        live.stop()
        return dict(live.record)

    def stop_all(self) -> None:
        for live in list(self._live.values()):
            if live.alive:
                live.stop()

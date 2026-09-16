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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncContextManager, Protocol

from core.message_box import MAX_PROMPT_CHARS
from core.plugin import INSTALL_HINT, find_plugin_root, plugin_version
from core.version import cli_version
from core.state import TERMINAL_PHASE_STATUSES, ai_root, append_jsonl, atomic_write_json, pid_is_running, utc_now

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
    plugin_dir: Path  # the plugin checkout Claude Code loads the skills from
    resume_from: str | None = None  # a Claude session id to reattach to instead of starting a fresh transcript


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
            return (
                f"claude-agent-sdk is not installed ({exc}); install the CLI with its `dashboard` extra "
                "(`uv tool install \"ai-scientist[dashboard] @ <wheel url>\"`, or `uv sync --extra dashboard` in a checkout)"
            )
        return None

    def open(self, spec: LaunchSpec) -> AsyncContextManager[SessionClient]:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        # A relaunch reattaches to the stored transcript. The SDK forbids `session_id` next to `resume`
        # unless the session forks, and forking would strand the id the operator copied, so only one is passed.
        ids: dict[str, Any] = {"resume": spec.resume_from} if spec.resume_from else {"session_id": spec.claude_session_id}
        options = ClaudeAgentOptions(
            cwd=str(spec.cwd),
            plugins=[{"type": "local", "path": str(spec.plugin_dir)}],
            setting_sources=["user", "project"],
            permission_mode=self.permission_mode,  # type: ignore[arg-type]
            system_prompt={"type": "preset", "preset": "claude_code"},
            model=self.model,
            **ids,
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


@dataclass
class RunPhase:
    """As much of `runs/<run-id>/loop-state.json` as the resume path needs."""

    exists: bool = False
    phase_status: str | None = None
    active: bool | None = None
    run_outcome: str | None = None

    @property
    def ended(self) -> bool:
        """The loop reached a terminal outcome: resuming it means reopening it under a new bar."""
        return self.phase_status in TERMINAL_PHASE_STATUSES


def read_run_phase(target_repo: Path, run_id: str) -> RunPhase:
    state = _read_json(ai_root(target_repo) / "runs" / run_id / "loop-state.json") if _safe_segment(run_id) else None
    if not isinstance(state, dict):
        return RunPhase()
    phase_status = state.get("phase_status")
    run_outcome = state.get("run_outcome")
    return RunPhase(
        exists=True,
        phase_status=phase_status if isinstance(phase_status, str) else None,
        active=state.get("active") if isinstance(state.get("active"), bool) else None,
        run_outcome=run_outcome if isinstance(run_outcome, str) else None,
    )


def note_required_reason(phase: RunPhase) -> str | None:
    """Reopening a run that already ended needs the operator to say what the new bar is."""
    if phase.ended:
        return f"a note is required to reopen a run that already ended ({phase.phase_status})"
    return None


def _check_note(note: str, phase: RunPhase) -> None:
    if len(note or "") > MAX_PROMPT_CHARS:
        raise SessionError(f"note longer than {MAX_PROMPT_CHARS} characters")
    reason = note_required_reason(phase)
    if reason and not (note or "").strip():
        raise SessionError(reason)


def build_resume_prompt(spec: LaunchSpec, note: str = "", last_event_at: str | None = None, phase: RunPhase | None = None) -> str:
    """The prompt a Resume sends, framed by what the run's loop-state.json says.

    Three cases: the loop is still running and the session went quiet, the loop already ended
    and the operator is reopening it under a tightened bar, or bootstrap never created the run.
    """
    phase = phase or RunPhase()
    since = f" since {last_event_at}" if last_event_at else ""
    goal = (
        f"/goal Complete the ai-scientist research campaign for run {spec.run_id}: the ai-scientist:research-loop skill must reach one of its "
        "terminal outcomes with completion audit and handoff evidence."
    )
    if not phase.exists:
        lines = [
            goal,
            f"Run id: {spec.run_id}. Target repository: {spec.cwd}.",
            f"Research contract: {spec.contract_path}. Idea batch: {spec.idea_batch}.",
            f"The dashboard resumed this session and `runs/{spec.run_id}/` does not exist yet, so the run still has to be bootstrapped. "
            "Check the target repository before assuming the earlier attempt left nothing behind.",
        ]
        if note.strip():
            lines += ["Note from the user:", note.strip()]
    elif phase.ended:
        outcome = f" (run_outcome {phase.run_outcome})" if phase.run_outcome else ""
        lines = [
            goal,
            f"The operator is reopening this run from the dashboard. Its loop-state.json reads phase_status \"{phase.phase_status}\"{outcome}, "
            "so the loop already terminated once and the bar it was judged against has been tightened.",
            "The new bar, from the operator:",
            note.strip(),
            "Re-read loop-state.json, journal.jsonl and the research contract, then judge the new bar against the evidence the run already produced. "
            "Say plainly if it is unreachable or already met rather than reopening for the sake of it.",
            "To reopen: record the new bar as a binding_amendment in the run state, put phase_status back to \"running\" with active true and no stale "
            "run_outcome, and journal the transition that did it so the durable state explains why the run is live again. Leave the previous outcome and "
            "its evidence in the journal; the reopened run terminates again under the research-loop terminal conditions, judged against the amended bar.",
        ]
    else:
        lines = [
            goal,
            f"The dashboard flagged this session as stalled: the run's loop-state.json still has phase_status \"running\" and no orchestrator activity{since}.",
            "Re-read loop-state.json and journal.jsonl and check the research-loop terminal conditions against the durable state, not your memory of the conversation. "
            "If the goal is not met, continue the campaign from that state. If it is met, checkpoint the terminal outcome so the run is no longer active.",
        ]
        if note.strip():
            lines += ["Note from the user:", note.strip()]
    return "\n".join(lines)


class LiveSession:
    def __init__(self, target_repo: Path, backend: SessionBackend, spec: LaunchSpec, record: dict[str, Any], prompt: str | None = None):
        self.target_repo = target_repo
        self.backend = backend
        self.spec = spec
        self.record = record
        # A relaunch opens with the resume prompt instead; the process restart also drops the /goal stop hook, so both re-arm it.
        self.prompt = prompt or build_launch_prompt(spec)
        self.first_origin = "resume" if spec.resume_from else "launch"
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._client: SessionClient | None = None
        self._loop_ready = threading.Event()
        self._started = threading.Event()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"session-{spec.session_id}", daemon=True)
        self.last_event_at: str | None = None

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
            self.last_event_at = event["ts"]
        return event

    # -- lifecycle
    def start(self) -> None:
        self._thread.start()

    def _warn_on_version_skew(self) -> None:
        """The skills come from the plugin checkout, the CLI from the wheel; note when their versions differ."""
        plugin, cli = plugin_version(self.spec.plugin_dir), cli_version()
        if plugin != cli:
            self.append_event({
                "type": "dashboard",
                "subtype": "version_skew",
                "text": f"plugin {self.spec.plugin_dir} is version {plugin or 'unknown'} but the CLI is {cli}; "
                "the skills and the CLI may disagree (update the plugin or reinstall the CLI)",
            })

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as exc:  # noqa: BLE001 - a dead thread must leave a readable record
            self._finish("failed", f"{exc.__class__.__name__}: {exc}")
        finally:
            self._loop_ready.set()
            self._started.set()
            self._done.set()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._loop_ready.set()
        try:
            async with self.backend.open(self.spec) as client:
                self._client = client
                self._started.set()
                self._warn_on_version_skew()
                await client.query(self.prompt)
                self.append_event({"type": "user", "origin": self.first_origin, "text": self.prompt})
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

    def send(self, text: str, origin: str = "dashboard") -> dict[str, Any]:
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
        event = self.append_event({"type": "user", "origin": origin, "text": text})
        future = asyncio.run_coroutine_threadsafe(self._client.query(text), self._loop)
        try:
            future.result(SEND_TIMEOUT_SEC)
        except Exception as exc:  # noqa: BLE001
            self.append_event({"type": "dashboard", "subtype": "send-failed", "text": f"{exc.__class__.__name__}: {exc}"})
            raise SessionError(f"could not deliver message: {exc.__class__.__name__}: {exc}", 502) from exc
        return event

    def resume(self, note: str = "", phase: RunPhase | None = None) -> dict[str, Any]:
        """Nudge an orchestrator whose process is still alive: this is a message, not a relaunch."""
        if len(note or "") > MAX_PROMPT_CHARS:
            raise SessionError(f"note longer than {MAX_PROMPT_CHARS} characters")
        return self.send(build_resume_prompt(self.spec, note or "", self.last_event_at, phase), origin="resume")

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
        self._loop_ready.wait(SEND_TIMEOUT_SEC)  # a stop right after launch must still reach the loop
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


def _last_event_ts(target_repo: Path, session_id: str) -> str | None:
    """The `ts` of the last readable events.jsonl row; a relaunched process has no in-memory history."""
    try:
        lines = (session_dir(target_repo, session_id) / "events.jsonl").read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        row = None
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("ts"), str):
            return row["ts"]
    return None


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
    def __init__(self, target_repo: Path, backend: SessionBackend | None = None, *, plugin_dir: Path | None = None):
        self.target_repo = target_repo.resolve()
        self.backend: SessionBackend = backend or ClaudeSdkBackend()
        self.plugin_dir = plugin_dir.resolve() if plugin_dir else None
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

    def _plugin_dir(self, recorded: Any = None) -> Path:
        """The plugin checkout to load: what the session used before if it is still there, else this dashboard's."""
        if isinstance(recorded, str) and recorded and Path(recorded).is_dir():
            return Path(recorded)
        found = find_plugin_root()
        plugin_dir = self.plugin_dir or (found[0] if found else None)
        if plugin_dir is None:
            raise SessionError(INSTALL_HINT, 503)
        return plugin_dir

    # -- actions
    def launch(self, contract_id: str, idea_ids: list[str], prompt: str, run_id: str | None = None) -> dict[str, Any]:
        reason = self.backend.unavailable_reason()
        if reason:
            raise SessionError(reason, 503)
        plugin_dir = self._plugin_dir()
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
                plugin_dir=plugin_dir,
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
                "plugin_dir": str(plugin_dir),
                "num_turns": 0,
                "rate_limits": {},
                "error": None,
            }
            atomic_write_json(session_dir(self.target_repo, session_id) / "ideas.json", {"session_id": session_id, "ideas": ideas})
            atomic_write_json(session_dir(self.target_repo, session_id) / "session.json", record)
            live = LiveSession(self.target_repo, self.backend, spec, record)
            self._live[session_id] = live
        snapshot = dict(record)  # taken before the thread can move the status past `starting`
        live.start()
        return snapshot

    def _require(self, session_id: str) -> LiveSession:
        live = self._live.get(session_id)
        if live is None:
            if session_dir(self.target_repo, session_id).is_dir() if _safe_segment(session_id) else False:
                raise SessionError(f"session {session_id} is not owned by this dashboard process", 409)
            raise SessionError(f"unknown session: {session_id}", 404)
        return live

    def send(self, session_id: str, text: str) -> dict[str, Any]:
        return self._require(session_id).send(text)

    def resume(self, session_id: str, note: str = "") -> dict[str, Any]:
        """Resume a halted session: a message when the process is still alive, a relaunch when it is gone."""
        live = self._live.get(session_id)
        if live is not None and live.alive:
            phase = read_run_phase(self.target_repo, str(live.record.get("run_id") or ""))
            _check_note(note, phase)
            return live.resume(note, phase)
        return self._relaunch(live.record if live is not None else self._record(session_id), note)

    def _record(self, session_id: str) -> dict[str, Any]:
        """The stored record for a session this process does not hold."""
        if not _safe_segment(session_id) or not session_dir(self.target_repo, session_id).is_dir():
            raise SessionError(f"unknown session: {session_id}", 404)
        record = _read_json(session_dir(self.target_repo, session_id) / "session.json")
        if not isinstance(record, dict):
            raise SessionError(f"session {session_id} has no readable session.json", 409)
        record["id"] = session_id
        return record

    def _relaunch(self, record: dict[str, Any], note: str) -> dict[str, Any]:
        """Start a process again for a session whose own one is gone, reattached to its Claude transcript."""
        session_id = str(record["id"])
        reason = self.backend.unavailable_reason()
        if reason:
            raise SessionError(reason, 503)
        pid = record.get("owner_pid")
        if record.get("status") in LIVE_STATUSES and isinstance(pid, int) and pid != os.getpid() and pid_is_running(pid):
            raise SessionError(f"session {session_id} is not owned by this dashboard process", 409)
        claude_session_id = record.get("claude_session_id")
        if not isinstance(claude_session_id, str) or not claude_session_id:
            raise SessionError(f"session {session_id} never reported a Claude session id, so there is no transcript to resume", 409)
        run_id = str(record.get("run_id") or "")
        if not _safe_segment(run_id):
            raise SessionError(f"session {session_id} has no usable run id")
        phase = read_run_phase(self.target_repo, run_id)
        _check_note(note, phase)
        plugin_dir = self._plugin_dir(record.get("plugin_dir"))
        ideas = _read_json(session_dir(self.target_repo, session_id) / "ideas.json")
        idea_ids = [i["id"] for i in (ideas or {}).get("ideas", []) if isinstance(i, dict) and isinstance(i.get("id"), str)] if isinstance(ideas, dict) else []
        with self._lock:
            for other in self._live.values():
                if other.alive and other.record.get("run_id") == run_id:
                    raise SessionError(f"run {run_id} already has a live session {other.spec.session_id}", 409)
            spec = LaunchSpec(
                session_id=session_id,
                claude_session_id=claude_session_id,
                run_id=run_id,
                cwd=self.target_repo,
                contract_path=str(record.get("contract_path") or ""),
                idea_batch=str(record.get("idea_batch") or ""),
                idea_ids=idea_ids,
                prompt=str(record.get("prompt") or ""),
                plugin_dir=plugin_dir,
                resume_from=claude_session_id,
            )
            prompt = build_resume_prompt(spec, note or "", _last_event_ts(self.target_repo, session_id), phase)
            record.update(status="starting", owner_pid=os.getpid(), error=None, plugin_dir=str(plugin_dir), updated_at=utc_now())
            atomic_write_json(session_dir(self.target_repo, session_id) / "session.json", record)
            live = LiveSession(self.target_repo, self.backend, spec, record, prompt=prompt)
            # The same directory and the same transcript: events.jsonl reads as one console across the restart.
            event = live.append_event({"type": "dashboard", "subtype": "relaunch", "text": f"resumed by the dashboard, reattached to Claude session {claude_session_id}"})
            self._live[session_id] = live
        live.start()
        return event

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

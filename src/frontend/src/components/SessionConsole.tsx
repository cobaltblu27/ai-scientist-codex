import { useState } from "react";
import { interruptSession, sendSessionMessage, stopSession, useSession } from "../lib/api";
import { isSessionLive, type SessionEvent, type SessionRecord } from "../lib/types";
import { relTime } from "../lib/format";
import { SessionBadge } from "./SessionBadge";
import { UsageMeter } from "./UsageMeter";

interface Props {
  /** run.session from the polled run detail; the console polls the session itself for events. */
  session: SessionRecord;
}

const EXCERPT = 300;

/** Rail card for a dashboard-owned Claude session: status, compose box, interrupt/stop, event tail. */
export function SessionConsole({ session: fromRun }: Props) {
  const { data, error: pollError, refresh } = useSession(fromRun.id);
  const session = data ?? fromRun;
  const live = isSessionLive(session);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"send" | "interrupt" | "stop" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(true);

  const act = async (kind: "send" | "interrupt" | "stop", fn: () => Promise<unknown>, done: string) => {
    if (busy) return;
    setBusy(kind);
    setError(null);
    setNote(null);
    try {
      await fn();
      setNote(done);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const send = () => {
    const body = text.trim();
    if (!body) return;
    void act("send", async () => {
      await sendSessionMessage(session.id, body);
      setText("");
    }, "sent to the session");
  };
  const interrupt = () => void act("interrupt", () => interruptSession(session.id), "interrupt requested");
  const stop = () => {
    if (!window.confirm(`Stop session ${session.id}? The Claude process is terminated; the run's files stay.`)) return;
    void act("stop", () => stopSession(session.id), "session stopped");
  };

  const events = data?.events ?? [];

  return (
    <div className={`card rail-card console ${live ? "lime" : ""}`}>
      <div className="tile-kicker">Session</div>
      <SessionBadge session={session} />
      <div className="muted">
        {session.backend} · {session.num_turns ?? 0} turns · updated {relTime(session.updated_at)}
      </div>
      <UsageMeter limits={session.rate_limits} />
      {session.error && <div className="msg-note orange">{session.error}</div>}
      {pollError && <div className="msg-note orange">{pollError}</div>}
      {!live && <div className="msg-note muted">not live; resume from a terminal with the copied id</div>}

      <form
        className="console-form"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <textarea
          rows={3}
          value={text}
          disabled={!live || busy !== null}
          placeholder={live ? "Message the orchestrator directly (delivered mid-turn)…" : "session is not live"}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="msg-actions">
          <button type="submit" className="pill ink" disabled={!live || busy !== null || text.trim().length === 0}>
            {busy === "send" ? "Sending…" : "Send"}
          </button>
          <button type="button" className="pill" disabled={!live || busy !== null} onClick={interrupt} title="Interrupt the current turn; the session stays open">
            {busy === "interrupt" ? "Interrupting…" : "Interrupt"}
          </button>
          <button type="button" className="pill orange" disabled={!live || busy !== null} onClick={stop} title="Terminate the Claude process">
            {busy === "stop" ? "Stopping…" : "Stop"}
          </button>
        </div>
        {error && <div className="msg-note orange">{error}</div>}
        {!error && note && <div className="msg-note muted">{note}</div>}
      </form>

      <button className="tile-kicker link-btn" onClick={() => setLogOpen(!logOpen)}>
        Events · {events.length} {logOpen ? "▾" : "▸"}
      </button>
      {logOpen && (
        <div className="console-log">
          {events.length === 0 && <div className="muted">no events yet</div>}
          {[...events].reverse().map((e, i) => (
            <EventRow key={`${e.ts}-${events.length - i}`} e={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function EventRow({ e }: { e: SessionEvent }) {
  const [full, setFull] = useState(false);
  const text = e.text ?? "";
  const long = text.length > EXCERPT;
  const shown = full || !long ? text : text.slice(0, EXCERPT - 1) + "…";
  const head = (
    <span className="console-head">
      <span className={`pill tiny ${e.type === "assistant" ? "lime" : e.type === "user" ? "pink" : e.type === "stderr" || e.subtype === "error" ? "orange" : ""}`}>
        {e.type}
        {e.subtype && e.type !== "user" ? ` · ${e.subtype}` : ""}
      </span>
      {e.type === "user" && e.origin && <span className="pill tiny">{e.origin}</span>}
      <span className="muted nowrap" title={e.ts}>{relTime(e.ts)}</span>
    </span>
  );
  return (
    <div className={`console-event ${e.type}`}>
      {head}
      {e.tool ? (
        <span className="mono">tool: {e.tool}</span>
      ) : (
        text && <span className={`console-text ${e.type === "stderr" ? "muted" : ""}`}>{shown}</span>
      )}
      {long && !e.tool && (
        <button type="button" className="link-btn muted msg-toggle" onClick={() => setFull(!full)}>
          {full ? "show less" : "show full"}
        </button>
      )}
    </div>
  );
}

import { useState } from "react";
import { sendMessage } from "../lib/api";
import type { SteerMessage } from "../lib/types";
import { relTime, tone } from "../lib/format";
import { Markdown } from "./Markdown";

interface Props {
  runId: string;
  nodeId: string;
  /** This node's messages, newest first (polled with the node detail). */
  messages: SteerMessage[];
  nodeAlive: boolean;
  /** null when the run has no readable state. */
  runActive: boolean | null;
  onOpenNode: (id: string) => void;
}

const EXCERPT = 120;

/** Compose form plus the per-node message list. No optimistic insert: the polled node detail brings the row. */
export function MessageBox({ runId, nodeId, messages, nodeAlive, runActive, onOpenNode }: Props) {
  return (
    <section>
      <h3 className="sub-title">
        Messages <sup>({messages.length})</sup>
      </h3>
      <Compose runId={runId} nodeId={nodeId} nodeAlive={nodeAlive} runActive={runActive} />
      {messages.length === 0 ? (
        <div className="muted">No messages for this node.</div>
      ) : (
        <div className="card list">
          {messages.map((m) => (
            <MessageRow key={m.id} m={m} onOpenNode={onOpenNode} />
          ))}
        </div>
      )}
    </section>
  );
}

function Compose({ runId, nodeId, nodeAlive, runActive }: { runId: string; nodeId: string; nodeAlive: boolean; runActive: boolean | null }) {
  const [picked, setKind] = useState<SteerMessage["kind"]>("revision");
  // A closed node is still a valid parent, so only `branch` stays available once the node leaves the live set.
  const kind: SteerMessage["kind"] = nodeAlive ? picked : "branch";
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<string | null>(null);

  const submit = async () => {
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setQueued(null);
    try {
      const rec = await sendMessage(runId, { node_id: nodeId, kind, prompt: text });
      setPrompt("");
      setQueued(rec.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="msg-form card"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="seg" role="radiogroup" aria-label="Message kind">
        <button
          type="button"
          role="radio"
          aria-checked={kind === "revision"}
          className={`pill ${kind === "revision" ? "active" : ""}`}
          disabled={!nodeAlive}
          title={nodeAlive ? "Revise this node in place" : "node is closed"}
          onClick={() => setKind("revision")}
        >
          revision
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={kind === "branch"}
          className={`pill ${kind === "branch" ? "active" : ""}`}
          title="Create a child of this node"
          onClick={() => setKind("branch")}
        >
          branch
        </button>
      </div>
      <textarea
        rows={4}
        value={prompt}
        placeholder="What should the orchestrator try on this node?"
        onChange={(e) => setPrompt(e.target.value)}
        disabled={busy}
      />
      <div className="msg-actions">
        <button type="submit" className="pill ink" disabled={busy || prompt.trim().length === 0}>
          {busy ? "Sending…" : "Send"}
        </button>
        {error && <span className="msg-note orange">{error}</span>}
        {!error && queued && <span className="msg-note muted">queued as {queued}</span>}
      </div>
      {runActive === false && <div className="msg-note muted">run is not active; the message waits for the next orchestrator session</div>}
    </form>
  );
}

function MessageRow({ m, onOpenNode }: { m: SteerMessage; onOpenNode: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const long = m.prompt.length > EXCERPT;
  const excerpt = long ? m.prompt.slice(0, EXCERPT - 1) + "…" : m.prompt;
  return (
    <div className="row msg-row">
      <span className={`dot ${tone(m.status)}`} />
      <span className="row-main">
        <span className="row-title">
          <span className={`pill tiny ${tone(m.status)}`}>{m.status}</span> <span className="pill tiny">{m.kind}</span>
          <span className="muted mono"> · {m.id}</span>
        </span>
        {open ? (
          <Markdown source={m.prompt} />
        ) : (
          <span className="row-sub msg-excerpt">{excerpt}</span>
        )}
        {long && (
          <button type="button" className="link-btn muted msg-toggle" onClick={() => setOpen(!open)}>
            {open ? "show less" : "show full"}
          </button>
        )}
        <span className="row-sub">
          {relTime(m.created_at)}
          {m.work_id && <> · work <span className="mono">{m.work_id}</span></>}
          {m.result_node_id && (
            <>
              {" "}· result{" "}
              <button type="button" className="link-btn" onClick={() => onOpenNode(m.result_node_id!)}>
                <b>{m.result_node_id}</b>
              </button>
            </>
          )}
        </span>
        {m.note && <span className={`msg-note ${m.status === "rejected" ? "orange" : "muted"}`}>{m.note}</span>}
      </span>
    </div>
  );
}

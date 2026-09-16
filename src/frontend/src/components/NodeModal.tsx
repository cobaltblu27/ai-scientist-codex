import { useEffect, useState } from "react";
import { useNode } from "../lib/api";
import type { NodeDetail, NodeHistoryEvent, NodeReport } from "../lib/types";
import { fmtTime, primaryMetric, relTime, statusKind, tone } from "../lib/format";
import { Markdown } from "./Markdown";
import { MessageBox } from "./MessageBox";

interface Props {
  runId: string;
  nodeId: string;
  primaryMetricName: string | null;
  /** run.active; null when the run has no readable state. */
  runActive: boolean | null;
  onClose: () => void;
  /** Open another node's modal (used by message rows that point at a result node). */
  onOpenNode: (id: string) => void;
}

export function NodeModal({ runId, nodeId, primaryMetricName, runActive, onClose, onOpenNode }: Props) {
  const { data, error } = useNode(runId, nodeId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={nodeId} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="min0">
            <div className="tile-kicker">node</div>
            <h2 className="ellipsis">
              {data?.title ? `${nodeId} · ${data.title}` : nodeId}
              {data && data.pending_messages > 0 && (
                <span className="pill tiny pink" style={{ marginLeft: 8, verticalAlign: "middle" }}>
                  {data.pending_messages} pending
                </span>
              )}
            </h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        {error && <div className="card banner orange">{error}</div>}
        {!data && !error && <div className="empty">Loading…</div>}
        {data && <Body d={data} runId={runId} nodeId={nodeId} metricName={primaryMetricName} runActive={runActive} onOpenNode={onOpenNode} />}
      </div>
    </div>
  );
}

/* Ledger keys the cards above already show; everything else in the ledger goes to the "more" table. */
const SHOWN = new Set(["status", "updated_at", "parent_node_id", "title", "idea_id", "assignment", "result_ref", "evidence_summary", "next_action", "metrics"]);

function Body({
  d, runId, nodeId, metricName, runActive, onOpenNode,
}: {
  d: NodeDetail;
  runId: string;
  nodeId: string;
  metricName: string | null;
  runActive: boolean | null;
  onOpenNode: (id: string) => void;
}) {
  const m = primaryMetric(d.metrics, metricName);
  const extra = Object.entries(d.ledger ?? {}).filter(([k]) => !SHOWN.has(k));
  const notes: [string, unknown][] = [
    ["assignment", d.assignment],
    ["evidence", d.evidence_summary],
    ["next action", d.next_action],
  ];
  return (
    <div className="modal-body">
      <section className="modal-grid">
        <div className={`card rail-card ${tone(d.status)}`}>
          <div className="tile-kicker">Status</div>
          <div className="rail-big">{d.status ?? "—"}</div>
          <div className="muted">
            {statusKind(d.status)} · {d.alive ? "live" : "closed"}
          </div>
          <div className="muted">
            {d.parent_node_id ? <>branched from <b>{d.parent_node_id}</b></> : "root node"} · depth {d.depth}
          </div>
          {d.idea_id && <div className="muted">idea: {d.idea_id}</div>}
          <div className="muted">updated {relTime(d.updated_at)}</div>
        </div>
        <div className="card rail-card">
          <div className="tile-kicker">Result</div>
          {m ? (
            <div>
              <span className="tile-big">{m.value}</span> <span className="muted">{m.key}</span>
            </div>
          ) : (
            <div className="muted">no metrics in ledger</div>
          )}
          <div className="muted">
            {d.work.length} work items · {d.report_count} reports
          </div>
        </div>
      </section>

      <MessageBox runId={runId} nodeId={nodeId} messages={d.messages ?? []} nodeAlive={d.alive} runActive={runActive} onOpenNode={onOpenNode} />

      {notes.some(([, v]) => v) && (
        <section>
          <dl className="notes">
            {notes.map(([label, v]) => v ? (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{String(v)}</dd>
              </div>
            ) : null)}
          </dl>
        </section>
      )}

      {d.metrics && Object.keys(d.metrics).length > 0 && (
        <section>
          <h3 className="sub-title">Metrics</h3>
          <table className="kv">
            <tbody>
              {Object.entries(d.metrics).map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td className="mono">{typeof v === "number" ? +v.toFixed(6) : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {d.work.length > 0 && (
        <section>
          <h3 className="sub-title">
            Work <sup>({d.work.length})</sup>
          </h3>
          <table className="kv">
            <tbody>
              {d.work.map((w) => (
                <tr key={w.work_id}>
                  <th>{w.work_id}</th>
                  <td>
                    <span className={`pill tiny ${tone(w.status)}`}>{w.status ?? "—"}</span>
                    {w.agent_thread_id && <span className="muted mono"> · {String(w.agent_thread_id)}</span>}
                    {w.next_action != null && <span className="muted"> · {String(w.next_action)}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {extra.length > 0 && (
        <section>
          <h3 className="sub-title">More from the ledger</h3>
          <table className="kv">
            <tbody>
              {extra.map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td>{typeof v === "object" ? <pre className="raw">{JSON.stringify(v, null, 2)}</pre> : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <Reports reports={d.reports} />
      <History events={d.history} />
    </div>
  );
}

function Reports({ reports }: { reports: NodeReport[] }) {
  const [idx, setIdx] = useState(reports.length - 1);
  const current = reports[Math.min(idx, reports.length - 1)] ?? null;
  return (
    <section>
      <h3 className="sub-title">
        Reports <sup>({reports.length})</sup>
      </h3>
      {reports.length === 0 ? (
        <div className="muted">
          No report file found. Reports are located through <code>result_ref</code> on the node ledger entry and its work items.
        </div>
      ) : (
        <>
          <div className="tabs">
            {reports.map((r, i) => (
              <button key={r.ref} className={`tab ${r === current ? "active" : ""}`} onClick={() => setIdx(i)} title={r.path ?? r.ref}>
                <span className="dot ink" />
                {r.work_id ?? r.name}
                <span className="muted"> · {relTime(r.updated_at)}</span>
              </button>
            ))}
          </div>
          {current && (
            <div className="report">
              <div className="muted mono ellipsis" title={current.path ?? current.ref}>{current.path ?? current.ref}</div>
              {current.content ? <Markdown source={current.content} /> : <div className="muted">unreadable</div>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function History({ events }: { events: NodeHistoryEvent[] }) {
  const rows = [...events].reverse();
  return (
    <section>
      <h3 className="sub-title">
        History <sup>({rows.length})</sup>
      </h3>
      {rows.length === 0 ? (
        <div className="muted">
          Nothing references this node yet. Journal records need <code>node_id</code>, work items need <code>node</code>.
        </div>
      ) : (
        <div className="card list">
          {rows.map((e, i) => (
            <div key={i} className="row">
              <span className={`dot ${e.kind === "report" ? "ink" : tone(e.kind === "work" ? e.status : undefined)}`} />
              <span className="row-main">
                <span className="row-title">
                  {e.kind === "journal" ? (e.event_type ?? "journal") : e.kind === "work" ? e.work_id : e.name}
                  {e.kind === "work" && e.status && <span className={`pill tiny ${tone(e.status)}`} style={{ marginLeft: 8 }}>{e.status}</span>}
                </span>
                <span className="row-sub ellipsis">
                  {e.kind === "journal" && String(e.details.note ?? e.details.command ?? e.subagent_id ?? summarize(e.details))}
                  {e.kind === "work" && summarize(e.details)}
                  {e.kind === "report" && (e.work_id ? `${e.work_id} · ` : "") + (e.path ?? "")}
                </span>
              </span>
              <span className="muted nowrap" title={e.timestamp ?? undefined}>{fmtTime(e.timestamp ?? e.epoch)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function summarize(details: Record<string, unknown>): string {
  const s = Object.entries(details)
    .filter(([k]) => k !== "status" && k !== "node")
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" ");
  return s.length > 90 ? s.slice(0, 87) + "…" : s;
}

import { useEffect, useState } from "react";
import { useNode } from "../lib/api";
import type { NodeDetail, NodeHistoryEvent, NodeReport } from "../lib/types";
import { fmtTime, primaryMetric, relTime, statusKind, tone } from "../lib/format";
import { Markdown } from "./Markdown";

interface Props {
  runId: string;
  nodeId: string;
  primaryMetricName: string | null;
  onClose: () => void;
}

export function NodeModal({ runId, nodeId, primaryMetricName, onClose }: Props) {
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
            <h2 className="ellipsis">{nodeId}</h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        {error && <div className="card banner orange">{error}</div>}
        {!data && !error && <div className="empty">Loading…</div>}
        {data && <Body d={data} metricName={primaryMetricName} />}
      </div>
    </div>
  );
}

function Body({ d, metricName }: { d: NodeDetail; metricName: string | null }) {
  const node = (d.node ?? {}) as Record<string, unknown>;
  const status = d.official_status ?? d.status;
  const m = primaryMetric(d.metrics, metricName);
  const checks: [string, unknown][] = [
    ["split integrity", node.split_integrity],
    ["leakage check", node.leakage_check],
    ["novelty", node.novelty],
  ];
  const notes: [string, unknown][] = [
    ["current claim", d.current_claim],
    ["rejection reason", node.rejection_reason],
    ["failure signature", node.failure_signature],
    ["fundamental failure", node.fundamental_failure_reason],
    ["worker recommendation", node.worker_recommendation],
  ];
  return (
    <div className="modal-body">
      <section className="modal-grid">
        <div className={`card rail-card ${tone(status)}`}>
          <div className="tile-kicker">Status</div>
          <div className="rail-big">{status ?? "—"}</div>
          <div className="muted">
            {statusKind(status)} · {d.alive ? "live" : "closed"}
            {d.official_status && d.status && d.official_status !== d.status && <> · node.json says {d.status}</>}
          </div>
          <div className="muted">
            {d.parent_node_id ? <>branched from <b>{d.parent_node_id}</b></> : "root node"} · depth {d.depth}
          </div>
          {d.outcome_type && <div className="muted">outcome: {d.outcome_type}</div>}
          <div className="muted">updated {relTime(d.updated_at)}</div>
        </div>
        <div className="card rail-card">
          <div className="tile-kicker">Result</div>
          {m ? (
            <div>
              <span className="tile-big">{m.value}</span> <span className="muted">{m.key}</span>
            </div>
          ) : (
            <div className="muted">no metrics yet</div>
          )}
          {d.result_summary && <div>{d.result_summary}</div>}
          <div className="muted">{d.trial_count} trials</div>
        </div>
      </section>

      {Object.keys(d.metrics).length > 0 && (
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

      {(checks.some(([, v]) => v) || notes.some(([, v]) => v)) && (
        <section>
          <h3 className="sub-title">Checks &amp; notes</h3>
          <div className="check-row">
            {checks.map(([label, v]) => {
              if (!v || typeof v !== "object") return null;
              const c = v as { pass?: boolean; summary?: string };
              return (
                <span key={label} className={`pill ${c.pass ? "lime" : "orange"}`} title={c.summary}>
                  {label}: {c.pass ? "pass" : "fail"}
                </span>
              );
            })}
          </div>
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

      <Reports reports={d.reports} nodeId={d.node_id} />
      <History events={d.history} />
    </div>
  );
}

function Reports({ reports, nodeId }: { reports: NodeReport[]; nodeId: string }) {
  const [idx, setIdx] = useState(reports.length - 1);
  const current = reports[Math.min(idx, reports.length - 1)] ?? null;
  return (
    <section>
      <h3 className="sub-title">
        Reports <sup>({reports.length})</sup>
      </h3>
      {reports.length === 0 ? (
        <div className="muted">
          No reports yet. Workers write <code>logs/workers/{nodeId}/&lt;worker-id&gt;/result.md</code>, revisions write{" "}
          <code>logs/revisions/{nodeId}/&lt;revision-id&gt;/result.md</code>.
        </div>
      ) : (
        <>
          <div className="tabs">
            {reports.map((r, i) => (
              <button key={r.path} className={`tab ${r === current ? "active" : ""}`} onClick={() => setIdx(i)} title={r.path}>
                <span className={`dot ${r.kind === "revision" ? "orange" : "lime"}`} />
                {r.agent_id}
                <span className="muted"> · {relTime(r.updated_at)}</span>
              </button>
            ))}
          </div>
          {current && (
            <div className="report">
              <div className="muted mono ellipsis" title={current.path}>{current.path}</div>
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
        <div className="muted">No journal events, work items or reports reference this node yet.</div>
      ) : (
        <div className="card list">
          {rows.map((e, i) => (
            <div key={i} className="row">
              <span className={`dot ${e.kind === "report" ? "ink" : tone(e.status ?? undefined)}`} />
              <span className="row-main">
                <span className="row-title">
                  {e.event_type ?? e.kind}
                  {e.status && <span className={`pill tiny ${tone(e.status)}`} style={{ marginLeft: 8 }}>{e.status}</span>}
                </span>
                <span className="row-sub ellipsis">
                  {e.agent_id ?? "orchestrator"}
                  {e.kind === "report" && <> · {String(e.details.path).split("/").slice(-3).join("/")}</>}
                  {e.kind !== "report" && Object.keys(e.details).length > 0 && <> · {summarize(e.details)}</>}
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
    .filter(([k]) => k !== "status")
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" ");
  return s.length > 90 ? s.slice(0, 87) + "…" : s;
}

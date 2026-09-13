import type { RunDetail } from "../lib/types";
import { primaryMetric, relTime, tone } from "../lib/format";
import { Stat } from "./Home";

export function RunView({ run }: { run: RunDetail }) {
  const nodes = [...run.nodes].sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0));
  const journal = [...run.journal].reverse();
  return (
    <>
      <header className="page-head">
        <div className="head-title">
          <h1 className="ellipsis">{run.run_id}</h1>
          <div className="muted">
            {run.phase ?? "—"} · <span className={`pill ${tone(run.phase_status)}`}>{run.phase_status ?? "—"}</span> · updated {relTime(run.updated_at)}
          </div>
        </div>
        <div className="head-stats">
          <Stat label="Nodes" value={run.node_count} />
          <Stat label="Ideas" value={run.idea_count} />
          <Stat label="Iteration" value={run.iteration ?? "—"} />
        </div>
      </header>

      {run.blocked_reason && <div className="card banner orange">Blocked: {run.blocked_reason}</div>}
      {run.goal && (
        <div className="card goal">
          <div className="tile-kicker">Goal</div>
          <div>{run.goal}</div>
        </div>
      )}

      <div className="two-col">
        <section>
          <h2 className="section-title">
            Nodes <sup>({nodes.length})</sup>
          </h2>
          {nodes.length === 0 ? (
            <div className="card empty">No nodes yet.</div>
          ) : (
            <div className="tile-grid">
              {nodes.map((n) => {
                const m = primaryMetric(n.metrics, run.primary_metric);
                const hi = n.node_id === run.selected_node ? "lime" : n.node_id === run.current_node ? "pink" : "";
                return (
                  <div key={n.node_id} className={`tile ${hi}`}>
                    <div className="tile-kicker">{n.outcome_type ?? n.status ?? "node"}</div>
                    <div className="tile-title ellipsis">{n.node_id}</div>
                    <div className="tile-big">{m ? m.value : "—"}</div>
                    <div className="tile-foot">
                      <span className="muted ellipsis">{m?.key ?? `${n.trial_count} trials`}</span>
                      <span className={`pill ${tone(n.status)}`}>{n.status ?? "—"}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <h2 className="section-title">
            Journal <sup>({run.journal_count})</sup>
          </h2>
          <div className="card list">
            {journal.length === 0 && <div className="empty">No journal events.</div>}
            {journal.map((e, i) => (
              <div key={i} className="row">
                <span className={`dot ${tone(String(e.details?.status ?? e.event_type))}`} />
                <span className="row-main">
                  <span className="row-title">{e.event_type}</span>
                  <span className="row-sub ellipsis">{e.node_id ?? e.transition_id ?? e.subagent_id ?? summarize(e.details)}</span>
                </span>
                <span className="muted nowrap">{relTime(e.timestamp)}</span>
              </div>
            ))}
          </div>
        </section>

        <aside className="rail">
          <div className="card rail-card lime">
            <div className="tile-kicker">Next action</div>
            <div className="rail-big">{run.next_action ?? "—"}</div>
            {run.current_node && <div className="muted">on {run.current_node}</div>}
          </div>
          <div className="card rail-card pink">
            <div className="tile-kicker">Selection</div>
            <div className="rail-big">{run.selected_node ?? "none"}</div>
            {run.selection && <div className="muted">{String((run.selection as { selection_status?: string }).selection_status ?? "")}</div>}
          </div>
          <div className="card rail-card">
            <div className="tile-kicker">Phases</div>
            <ul className="phase-list">
              {["ideation", "research", "review", "writeup"].map((p) => {
                const done = run.completed_phases.includes(p);
                const cur = run.phase === p;
                return (
                  <li key={p} className={done ? "done" : cur ? "current" : ""}>
                    <span className={`dot ${done ? "lime" : cur ? "orange" : "neutral"}`} />
                    {p}
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="card rail-card">
            <div className="tile-kicker">Artifacts</div>
            <div className="muted mono ellipsis" title={run.path}>{run.path}</div>
          </div>
        </aside>
      </div>
    </>
  );
}

function summarize(details: Record<string, unknown> | undefined): string {
  if (!details) return "";
  const s = JSON.stringify(details);
  return s.length > 80 ? s.slice(0, 77) + "…" : s;
}

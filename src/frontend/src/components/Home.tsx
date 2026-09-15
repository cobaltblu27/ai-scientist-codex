import type { Overview } from "../lib/types";
import { fmtDate, relTime, tone } from "../lib/format";
import { SessionBadge } from "./SessionBadge";
import { isSessionLive } from "../lib/types";
import { fmtPercent, windowLabel } from "../lib/format";
import { peakUsage, UsageMeter } from "./UsageMeter";

export function Home({ overview, onSelect, onStart }: { overview: Overview; onSelect: (id: string) => void; onStart: () => void }) {
  const runs = overview.runs;
  const sessions = overview.sessions ?? [];
  const active = runs.filter((r) => r.active);
  // Newest session that reported usage, live ones first: the subscription window the campaign is drawing on.
  const usageSession = [...sessions].sort((a, b) => Number(isSessionLive(b)) - Number(isSessionLive(a))).find((s) => peakUsage(s.rate_limits));
  const usage = peakUsage(usageSession?.rate_limits);
  return (
    <>
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <div className="muted">{fmtDate()}</div>
        </div>
        <div className="head-stats">
          <Stat label="Runs" value={runs.length} />
          <Stat label="Active" value={active.length} />
          <Stat label="Contracts" value={overview.contracts.length} />
          {usage && <Stat label={`Usage · ${windowLabel(usage.type)}`} value={fmtPercent(usage.utilization)} />}
        </div>
      </header>

      {!overview.exists && (
        <div className="card empty">
          No <code>.ai-scientist/</code> directory under <code>{overview.target_repo}</code>. Start a run or point the dashboard at another repo with{" "}
          <code>--target-repo</code>.
        </div>
      )}

      <h2 className="section-title">
        Runs <sup>({runs.length})</sup>
      </h2>
      {runs.length === 0 ? (
        <div className="card empty">
          <div>No runs yet.</div>
          <button type="button" className="pill start-btn" onClick={onStart} style={{ marginTop: 12 }}>
            ▶ Start research
          </button>
        </div>
      ) : (
        <div className="tile-grid">
          {runs.map((r, i) => (
            <button key={r.run_id} className={`tile ${i === 0 && r.active ? "lime" : ""}`} onClick={() => onSelect(r.run_id)}>
              <div className="tile-kicker">{r.phase ?? "no phase"}</div>
              <div className="tile-title ellipsis">{r.run_id}</div>
              <div className="tile-big">{r.node_count}</div>
              <div className="tile-foot">
                <span className={`pill ${tone(r.phase_status)}`}>{r.phase_status ?? "—"}</span>
                {r.pending_messages > 0 && <span className="pill tiny pink">{r.pending_messages} msgs</span>}
                {r.session && <span className={`pill tiny ${tone(r.session.status)}`}>session · {r.session.status}</span>}
                <span className="muted">{relTime(r.updated_at ?? r.mtime)}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      <h2 className="section-title">
        Sessions <sup>({sessions.length})</sup>
      </h2>
      {sessions.length === 0 ? (
        <div className="card empty">No dashboard-owned sessions. Start research to launch one.</div>
      ) : (
        <div className="card list">
          {sessions.map((s) => (
            <div key={s.id} className="row">
              <span className={`dot ${tone(s.status)}`} />
              <span className="row-main">
                <span className="row-title">
                  {s.run_id ? (
                    <button type="button" className="link-btn" onClick={() => onSelect(s.run_id!)} title="open run">
                      {s.run_id}
                    </button>
                  ) : (
                    <span className="muted">no run yet</span>
                  )}
                </span>
                <span className="row-sub ellipsis">
                  {s.id} · {relTime(s.updated_at)}
                  {s.error && <span className="orange"> · {s.error}</span>}
                </span>
              </span>
              <UsageMeter limits={s.rate_limits} compact />
              <SessionBadge session={s} compact />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

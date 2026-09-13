import type { Overview } from "../lib/types";
import { fmtDate, relTime, tone } from "../lib/format";

export function Home({ overview, onSelect }: { overview: Overview; onSelect: (id: string) => void }) {
  const runs = overview.runs;
  const active = runs.filter((r) => r.active);
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
        <div className="card empty">No runs yet.</div>
      ) : (
        <div className="tile-grid">
          {runs.map((r, i) => (
            <button key={r.run_id} className={`tile ${i === 0 && r.active ? "lime" : ""}`} onClick={() => onSelect(r.run_id)}>
              <div className="tile-kicker">{r.phase ?? "no phase"}</div>
              <div className="tile-title ellipsis">{r.run_id}</div>
              <div className="tile-big">{r.node_count}</div>
              <div className="tile-foot">
                <span className={`pill ${tone(r.phase_status)}`}>{r.phase_status ?? "—"}</span>
                <span className="muted">{relTime(r.updated_at ?? r.mtime)}</span>
              </div>
            </button>
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

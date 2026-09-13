import type { Overview } from "../lib/types";
import { relTime, tone } from "../lib/format";

interface Props {
  overview: Overview | null;
  selected: string | null;
  onSelect: (runId: string | null) => void;
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ overview, selected, onSelect, open, onClose }: Props) {
  const runs = overview?.runs ?? [];
  const activeId = overview?.active_run?.run_id ?? null;
  const live = runs.filter((r) => r.active);
  const done = runs.filter((r) => !r.active);

  const pick = (id: string | null) => {
    onSelect(id);
    onClose();
  };

  return (
    <>
      <div className={`scrim ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span>AI Scientist</span>
          <button className="icon-btn close-btn" onClick={onClose} aria-label="Close menu">×</button>
        </div>

        <nav className="nav">
          <button className={`nav-item ${selected === null ? "active" : ""}`} onClick={() => pick(null)}>
            <span className="nav-ico">⌂</span> Home
          </button>
        </nav>

        <div className="section-head">
          <span>Loop runs</span>
          <span className="count">{runs.length}</span>
        </div>
        <RunGroup title="Active" runs={live} selected={selected} activeId={activeId} onPick={pick} />
        <RunGroup title="Finished" runs={done} selected={selected} activeId={activeId} onPick={pick} />

        <div className="section-head">
          <span>Contracts</span>
          <span className="count">{overview?.contracts.length ?? 0}</span>
        </div>
        <ul className="tree">
          {(overview?.contracts ?? []).map((c) => (
            <li key={c.contract_id} className="tree-item" title={c.goal ?? ""}>
              <span className={`dot ${c.valid ? "lime" : "orange"}`} />
              <span className="ellipsis">{c.contract_id}</span>
            </li>
          ))}
          {overview && overview.contracts.length === 0 && <li className="tree-item muted">none</li>}
        </ul>

        <div className="sidebar-foot">
          <div className="muted ellipsis" title={overview?.ai_root}>{overview?.ai_root ?? "…"}</div>
        </div>
      </aside>
    </>
  );
}

function RunGroup({
  title,
  runs,
  selected,
  activeId,
  onPick,
}: {
  title: string;
  runs: Overview["runs"];
  selected: string | null;
  activeId: string | null;
  onPick: (id: string) => void;
}) {
  if (runs.length === 0) return null;
  return (
    <ul className="tree">
      <li className="tree-label">{title}</li>
      {runs.map((r) => (
        <li key={r.run_id}>
          <button className={`tree-item run-item ${selected === r.run_id ? "active" : ""}`} onClick={() => onPick(r.run_id)}>
            <span className={`dot ${tone(r.phase_status)}`} />
            <span className="run-main">
              <span className="ellipsis">{r.run_id}</span>
              <span className="run-sub">
                {r.phase ?? "—"} · {relTime(r.updated_at ?? r.mtime)}
              </span>
            </span>
            {r.run_id === activeId && <span className="pill tiny">live</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

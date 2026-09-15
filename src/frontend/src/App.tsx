import { useCallback, useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { Home } from "./components/Home";
import { RunView } from "./components/RunView";
import { StartResearchModal } from "./components/StartResearchModal";
import { useOverview, useRun } from "./lib/api";

function runFromHash(): string | null {
  const m = window.location.hash.match(/^#\/runs\/(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

export default function App() {
  const [selected, setSelected] = useState<string | null>(runFromHash);
  const [menuOpen, setMenuOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const closeStart = useCallback(() => setStarting(false), []);
  const overview = useOverview();
  const run = useRun(selected);

  useEffect(() => {
    const onHash = () => setSelected(runFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const select = (id: string | null) => {
    window.location.hash = id ? `#/runs/${encodeURIComponent(id)}` : "";
    setSelected(id);
  };

  const error = run.error ?? overview.error;

  return (
    <div className="shell">
      <Sidebar overview={overview.data} selected={selected} onSelect={select} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <main className="main">
        <div className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMenuOpen(true)} aria-label="Open menu">☰</button>
          <div className="topbar-title ellipsis">{selected ?? "Home"}</div>
          <div className="topbar-right">
            {overview.data?.active_run && (
              <span className="pill lime" title="active-run.json">
                live: {overview.data.active_run.run_id}
              </span>
            )}
            <button className="pill start-btn" onClick={() => setStarting(true)} disabled={!overview.data} title="Launch a research loop in a dashboard-owned Claude session">
              ▶ Start research
            </button>
            <button className="icon-btn" onClick={() => { overview.refresh(); run.refresh(); }} title="Refresh">↻</button>
          </div>
        </div>
        {error && <div className="card banner orange">{error}</div>}
        {selected ? (
          run.data ? <RunView run={run.data} /> : !error && <div className="card empty">Loading {selected}…</div>
        ) : overview.data ? (
          <Home overview={overview.data} onSelect={select} onStart={() => setStarting(true)} />
        ) : (
          !error && <div className="card empty">Scanning…</div>
        )}
      </main>
      {starting && overview.data && (
        <StartResearchModal
          overview={overview.data}
          onClose={closeStart}
          onLaunched={(runId) => {
            overview.refresh();
            if (runId) setSelected(runId);
          }}
        />
      )}
    </div>
  );
}

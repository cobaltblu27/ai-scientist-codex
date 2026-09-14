import { useState } from "react";
import { useRunFile } from "../lib/api";
import type { ReportEntry } from "../lib/types";
import { relTime } from "../lib/format";
import { Markdown } from "./Markdown";

/** Run-level Markdown reports (any *.md under the run root or logs/), opened on demand through the files route. */
export function ReportPane({ runId, reports }: { runId: string; reports: ReportEntry[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const { text, error } = useRunFile(runId, open);
  const sorted = [...reports].sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0));
  return (
    <section>
      <h2 className="section-title">
        Reports <sup>({reports.length})</sup>
      </h2>
      {reports.length === 0 ? (
        <div className="card empty">No Markdown reports under the run root or logs/ yet.</div>
      ) : (
        <div className="card list">
          {sorted.map((r) => (
            <div key={r.path}>
              <button className={`row row-btn ${open === r.path ? "active" : ""}`} onClick={() => setOpen(open === r.path ? null : r.path)}>
                <span className="dot ink" />
                <span className="row-main">
                  <span className="row-title">{r.name}</span>
                  <span className="row-sub ellipsis mono">{r.path}</span>
                </span>
                <span className="muted nowrap">{relTime(r.updated_at)}</span>
              </button>
              {open === r.path && (
                <div className="report">
                  {error && <div className="muted">{error}</div>}
                  {text != null ? <Markdown source={text} /> : !error && <div className="muted">Loading…</div>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

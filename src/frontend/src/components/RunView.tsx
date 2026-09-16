import { useCallback, useState } from "react";
import { isSessionStalled, type RunDetail, type SteerMessage } from "../lib/types";
import { relTime, tone } from "../lib/format";
import { Stat } from "./Home";
import { NodeGraph } from "./NodeGraph";
import { NodeModal } from "./NodeModal";
import { ReportPane } from "./ReportPane";
import { Markdown } from "./Markdown";
import { SessionBadge } from "./SessionBadge";
import { SessionConsole } from "./SessionConsole";

export function RunView({ run }: { run: RunDetail }) {
  const [openNode, setOpenNode] = useState<string | null>(null);
  const closeNode = useCallback(() => setOpenNode(null), []);
  const ideation = run.phase === "ideation";
  const live = run.nodes.filter((n) => n.alive).length;
  return (
    <>
      <header className="page-head">
        <div className="head-title">
          <h1 className="ellipsis">{run.run_id}</h1>
          <div className="muted">
            {run.phase ?? "no phase"} · <span className={`pill ${tone(run.phase_status)}`}>{run.phase_status ?? "—"}</span>
            {run.active === false && run.phase_status && <> · finished</>}
            {run.updated_at && <> · updated {relTime(run.updated_at)}</>}
          </div>
          {run.session && (
            <div className="head-session">
              <SessionBadge session={run.session} />
              {isSessionStalled(run.session, run.active) && <span className="pill tiny orange">stalled</span>}
            </div>
          )}
        </div>
        <div className="head-stats">
          {ideation ? <Stat label="Ideas" value={run.idea_count ?? "—"} /> : <Stat label="Nodes" value={run.node_count} />}
          {!ideation && <Stat label="Live" value={live} />}
          {!ideation && <Stat label="Pending msgs" value={run.pending_messages ?? 0} />}
        </div>
      </header>

      {run.pending && (
        <div className="card banner lime">
          Starting: the session is bootstrapping this run. Nodes and reports appear once the orchestrator writes <code>loop-state.json</code>.
        </div>
      )}
      {isSessionStalled(run.session, run.active) && (
        <div className="card banner orange">
          Stalled: the run is still <code>{run.phase_status}</code> but its session went idle {relTime(run.session!.updated_at)}. Use <b>Resume</b> in the session card to
          nudge the orchestrator, or answer its question there.
        </div>
      )}
      {run.blocked_reason && <div className="card banner orange">Blocked: {run.blocked_reason}</div>}
      {run.phase === null && (
        <div className="card banner orange">
          This directory has neither <code>loop-state.json</code> nor <code>run.md</code>, so nothing can be read from it.
        </div>
      )}
      {run.goal && (
        <div className="card goal">
          <div className="tile-kicker">Goal</div>
          <div>{run.goal}</div>
        </div>
      )}

      {ideation ? <IdeationBody run={run} /> : <ResearchBody run={run} live={live} onOpen={setOpenNode} />}
      {openNode && (
        <NodeModal
          runId={run.run_id}
          nodeId={openNode}
          primaryMetricName={run.primary_metric}
          runActive={run.active}
          onClose={closeNode}
          onOpenNode={setOpenNode}
        />
      )}
    </>
  );
}

function ResearchBody({ run, live, onOpen }: { run: RunDetail; live: number; onOpen: (id: string) => void }) {
  const journal = [...run.journal].reverse();
  return (
    <div className="two-col">
      <section>
        <h2 className="section-title">
          Node tree <sup>({run.nodes.length} nodes · {live} live)</sup>
        </h2>
        {run.nodes.length === 0 ? (
          <div className="card empty">No nodes in <code>loop-state.json</code> yet.</div>
        ) : (
          <NodeGraph nodes={run.nodes} primaryMetricName={run.primary_metric} selectedNode={run.selected_node} onOpen={onOpen} />
        )}

        <ReportPane runId={run.run_id} reports={run.reports} />

        <h2 className="section-title">
          Journal <sup>({run.journal_count})</sup>
        </h2>
        <div className="card list">
          {journal.length === 0 && <div className="empty">No journal events.</div>}
          {journal.map((e, i) => (
            <div key={i} className="row">
              <span className={`dot ${tone(String(e.details?.status ?? ""))}`} />
              <span className="row-main">
                <span className="row-title">
                  {e.event_type}
                  {e.node_id && <span className="pill tiny" style={{ marginLeft: 8 }}>{e.node_id}</span>}
                </span>
                <span className="row-sub ellipsis">{String(e.details?.note ?? e.details?.command ?? e.transition_id ?? summarize(e.details))}</span>
              </span>
              <span className="muted nowrap">{relTime(e.timestamp)}</span>
            </div>
          ))}
        </div>
      </section>

      <aside className="rail">
        {run.session && <SessionConsole session={run.session} run={{ active: run.active, phase_status: run.phase_status }} />}
        <div className="card rail-card lime">
          <div className="tile-kicker">Next action</div>
          <div className="rail-big">{run.next_action ?? "—"}</div>
        </div>
        <div className="card rail-card pink">
          <div className="tile-kicker">Selection</div>
          <div className="rail-big">{run.selected_node ?? "none"}</div>
          <div className="muted">{run.selection_status ?? "no selection state"}</div>
        </div>
        <div className="card rail-card">
          <div className="tile-kicker">Contract</div>
          {run.primary_metric ? (
            <div>
              <b>{run.primary_metric}</b>
              {run.success_threshold != null && <> · threshold {String(run.success_threshold)}</>}
              {run.primary_metric_direction && <div className="muted">{run.primary_metric_direction.split("_").join(" ")}</div>}
            </div>
          ) : (
            <div className="muted">no config.md frontmatter</div>
          )}
          {run.baseline_status && <div className="muted">baseline: {run.baseline_status}</div>}
        </div>
        <MessagesCard messages={run.messages ?? []} pending={run.pending_messages ?? 0} onOpen={onOpen} />
        <RawPanel title="Open questions" value={run.open_questions} />
        <RawPanel title="Resources" value={run.resources} />
        <RawPanel title="Resource queue" value={run.resource_queue} />
        <div className="card rail-card">
          <div className="tile-kicker">Artifacts</div>
          <div className="muted mono ellipsis" title={run.path}>{run.path}</div>
          {run.links &&
            Object.entries(run.links).map(([k, v]) => (
              <div key={k} className="muted mono ellipsis" title={String(v)}>
                {k}: {String(v)}
              </div>
            ))}
        </div>
      </aside>
    </div>
  );
}

function IdeationBody({ run }: { run: RunDetail }) {
  return (
    <div className="two-col">
      <section>
        <h2 className="section-title">
          Ideas <sup>({run.ideas?.length ?? 0})</sup>
        </h2>
        {!run.ideas || run.ideas.length === 0 ? (
          <div className="card empty">No <code>ideas.json</code> yet.</div>
        ) : (
          <div className="card list">
            {run.ideas.map((idea, i) => (
              <div key={idea.id ?? i} className="row">
                <span className="dot lime" />
                <span className="row-main">
                  <span className="row-title">{idea.title ?? idea.id ?? `idea ${i + 1}`}</span>
                  <span className="row-sub ellipsis mono">{idea.idea_file ?? ""}{idea.pilot_report ? ` · ${idea.pilot_report}` : ""}</span>
                </span>
              </div>
            ))}
          </div>
        )}
        <ReportPane runId={run.run_id} reports={run.reports} />
      </section>
      <aside className="rail">
        {run.session && <SessionConsole session={run.session} run={{ active: run.active, phase_status: run.phase_status }} />}
        <div className="card rail-card">
          <div className="tile-kicker">run.md</div>
          {run.run_md ? <Markdown source={run.run_md} /> : <div className="muted">missing</div>}
        </div>
      </aside>
    </div>
  );
}

/** Run-wide steering queue: pending count plus the five most recent messages, each opening its node. */
function MessagesCard({ messages, pending, onOpen }: { messages: SteerMessage[]; pending: number; onOpen: (id: string) => void }) {
  const recent = messages.slice(0, 5);
  return (
    <div className={`card rail-card ${pending > 0 ? "pink" : ""}`}>
      <div className="tile-kicker">Messages</div>
      <div className="rail-big">{pending}</div>
      <div className="muted">pending · {messages.length} total</div>
      {recent.length > 0 && (
        <div className="msg-recent">
          {recent.map((m) => (
            <button key={m.id} type="button" className="row row-btn" onClick={() => onOpen(m.node_id)} title={m.prompt}>
              <span className={`dot ${tone(m.status)}`} />
              <span className="row-main">
                <span className="row-title">
                  {m.node_id} <span className="pill tiny">{m.kind}</span>
                </span>
                <span className="row-sub ellipsis">{m.prompt}</span>
              </span>
              <span className={`pill tiny ${tone(m.status)}`}>{m.status}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RawPanel({ title, value }: { title: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  if (value == null || (typeof value === "object" && Object.keys(value as object).length === 0)) return null;
  const count = typeof value === "object" ? Object.keys(value as object).length : 1;
  return (
    <div className="card rail-card">
      <button className="tile-kicker link-btn" onClick={() => setOpen(!open)}>
        {title} · {count} {open ? "▾" : "▸"}
      </button>
      {open && <pre className="raw">{JSON.stringify(value, null, 2)}</pre>}
    </div>
  );
}

function summarize(details: Record<string, unknown> | undefined): string {
  if (!details) return "";
  const s = JSON.stringify(details);
  return s.length > 80 ? s.slice(0, 77) + "…" : s;
}

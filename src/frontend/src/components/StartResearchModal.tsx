import { useEffect, useMemo, useState } from "react";
import { launchSession } from "../lib/api";
import type { Overview } from "../lib/types";

interface Props {
  overview: Overview;
  onClose: () => void;
  /** Called after a 201 so the caller can refresh the overview. */
  onLaunched: (runId: string | null) => void;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** `${YYYYMMDD}-${HHMM}-research-${contract}` in local time; the server uses the same shape in UTC. */
export function defaultRunId(contractId: string, d = new Date()): string {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}-research-${contractId}`;
}

/** Pick a contract and ideas, add instructions, and launch a server-owned Claude session. */
export function StartResearchModal({ overview, onClose, onLaunched }: Props) {
  const firstValid = overview.contracts.find((c) => c.valid)?.contract_id ?? null;
  const [contract, setContract] = useState<string | null>(firstValid);
  const [ideas, setIdeas] = useState<Set<string>>(() => new Set());
  const [prompt, setPrompt] = useState("");
  const [runId, setRunId] = useState(() => (firstValid ? defaultRunId(firstValid) : ""));
  const [runIdTouched, setRunIdTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const pickContract = (id: string) => {
    setContract(id);
    if (!runIdTouched) setRunId(defaultRunId(id));
  };

  const toggleIdea = (id: string) => {
    setIdeas((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const ideaCount = useMemo(() => overview.ideas.reduce((n, e) => n + e.ideas.length, 0), [overview.ideas]);
  const ready = !!contract && ideas.size > 0 && !busy;

  const launch = async () => {
    if (!ready || !contract) return;
    setBusy(true);
    setError(null);
    try {
      const id = runId.trim();
      const rec = await launchSession({ contract_id: contract, idea_ids: [...ideas], prompt: prompt.trim(), ...(id ? { run_id: id } : {}) });
      const target = rec.run_id ?? (id || null);
      onClose();
      if (target) window.location.hash = `#/runs/${encodeURIComponent(target)}`;
      onLaunched(target);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Start research" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="min0">
            <div className="tile-kicker">research loop</div>
            <h2 className="ellipsis">Start research</h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>

        <form
          className="modal-body"
          onSubmit={(e) => {
            e.preventDefault();
            void launch();
          }}
        >
          <section>
            <h3 className="sub-title">
              Contract <sup>({overview.contracts.length})</sup>
            </h3>
            {overview.contracts.length === 0 ? (
              <div className="muted">
                No contracts under <code>.ai-scientist/contracts/</code>. Write one first.
              </div>
            ) : (
              <div className="choice-list card">
                {overview.contracts.map((c) => (
                  <label key={c.contract_id} className={`choice ${c.valid ? "" : "disabled"} ${contract === c.contract_id ? "active" : ""}`}>
                    <input type="radio" name="contract" value={c.contract_id} disabled={!c.valid || busy} checked={contract === c.contract_id} onChange={() => pickContract(c.contract_id)} />
                    <span className="row-main">
                      <span className="row-title">
                        {c.contract_id}
                        {!c.valid && <span className="pill tiny orange" style={{ marginLeft: 8 }}>invalid</span>}
                      </span>
                      {c.goal && <span className="row-sub">{c.goal}</span>}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </section>

          <section>
            <h3 className="sub-title">
              Ideas <sup>({ideas.size} of {ideaCount} selected)</sup>
            </h3>
            {ideaCount === 0 ? (
              <div className="muted">No ideas yet. Run the ideation skill first.</div>
            ) : (
              overview.ideas.map((entry) => (
                <div key={entry.run_id} className="choice-group">
                  <div className="tile-kicker ellipsis" title={entry.goal ?? undefined}>
                    {entry.run_id}
                    {entry.goal && <span className="muted" style={{ textTransform: "none", letterSpacing: 0 }}> · {entry.goal}</span>}
                  </div>
                  <div className="choice-list card">
                    {entry.ideas.map((idea) => (
                      <label key={`${entry.run_id}/${idea.id}`} className={`choice ${ideas.has(idea.id) ? "active" : ""}`}>
                        <input type="checkbox" value={idea.id} disabled={busy} checked={ideas.has(idea.id)} onChange={() => toggleIdea(idea.id)} />
                        <span className="row-main">
                          <span className="row-title">{idea.title ?? idea.id}</span>
                          <span className="row-sub mono ellipsis">
                            {idea.id}
                            {idea.idea_file && <> · {idea.idea_file}</>}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ))
            )}
          </section>

          <section>
            <h3 className="sub-title">Instructions</h3>
            <textarea
              rows={5}
              value={prompt}
              disabled={busy}
              placeholder="Anything preflight would otherwise ask: which Python environment to use, resource caps (GPU hours, wall clock), datasets to avoid, evaluation notes…"
              onChange={(e) => setPrompt(e.target.value)}
            />
          </section>

          <section>
            <h3 className="sub-title">Run id</h3>
            <input
              className="text-input mono"
              type="text"
              value={runId}
              disabled={busy}
              placeholder="leave blank to let the server choose"
              onChange={(e) => {
                setRunIdTouched(true);
                setRunId(e.target.value);
              }}
            />
          </section>

          <div className="msg-actions">
            <button type="submit" className="pill ink" disabled={!ready}>
              {busy ? "Launching…" : "▶ Launch"}
            </button>
            {error && <span className="msg-note orange">{error}</span>}
            {!error && !contract && overview.contracts.length > 0 && <span className="msg-note muted">pick a valid contract</span>}
            {!error && contract && ideas.size === 0 && ideaCount > 0 && <span className="msg-note muted">pick at least one idea</span>}
          </div>
          <div className="msg-note muted">Runs unattended in the target repo with permissions bypassed.</div>
        </form>
      </div>
    </div>
  );
}

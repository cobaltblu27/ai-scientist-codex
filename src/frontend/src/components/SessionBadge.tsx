import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { SessionRecord } from "../lib/types";
import { tone } from "../lib/format";

interface Props {
  session: SessionRecord;
  /** Tile / list variant: tiny pill and a shortened id. */
  compact?: boolean;
}

/** Status pill plus the Claude session id, copyable for `claude --resume <id>`. */
export function SessionBadge({ session, compact = false }: Props) {
  const id = session.claude_session_id;
  const resume = id ? `claude --resume ${id}` : null;
  return (
    <span className={`session-badge ${compact ? "compact" : ""}`} title={resume ?? "the session has not reported its id yet"}>
      <span className={`pill ${compact ? "tiny" : ""} ${tone(session.status)}`}>{session.status}</span>
      <span className={`mono ${id ? "" : "muted"} ellipsis`}>{id ? (compact ? id.slice(0, 8) : id) : "no id yet"}</span>
      {id && <CopyButton text={id} label={resume!} />}
    </span>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const copy = async (e: MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    const ok = await writeClipboard(text);
    setCopied(ok);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button type="button" className={`copy-btn ${copied ? "lime" : ""}`} onClick={(e) => void copy(e)} title={label} aria-label={`Copy session id (${label})`}>
      {copied ? "copied" : "copy"}
    </button>
  );
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path (insecure context, denied permission) */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

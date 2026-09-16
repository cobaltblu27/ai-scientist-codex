import { useCallback, useEffect, useState } from "react";
import type { NodeDetail, Overview, RunDetail, SessionDetail, SessionEvent, SessionRecord, SteerMessage } from "./types";

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.error) msg = body.error;
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

async function getJson<T>(url: string): Promise<T> {
  return unwrap<T>(await fetch(url, { cache: "no-store" }));
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  return unwrap<T>(
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  );
}

/** Queue a human steering message for a node; the orchestrator picks it up at its next sweep. */
export function sendMessage(runId: string, body: { node_id: string; kind: SteerMessage["kind"]; prompt: string }): Promise<SteerMessage> {
  return postJson<SteerMessage>(`/api/runs/${encodeURIComponent(runId)}/messages`, body);
}

/* ---- dashboard-owned Claude sessions ---- */

export interface LaunchBody {
  contract_id: string;
  idea_ids: string[];
  prompt: string;
  /** Omitted when the user left the run id blank; the server then picks one. */
  run_id?: string;
}

/** Start a research campaign in a server-owned Claude session. 201 -> the new record. */
export function launchSession(body: LaunchBody): Promise<SessionRecord> {
  return postJson<SessionRecord>("/api/sessions", body);
}

const sessionUrl = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;

/** Push a follow-up message straight into the running session. 202 -> the recorded user event. */
export function sendSessionMessage(id: string, text: string): Promise<SessionEvent> {
  return postJson<SessionEvent>(`${sessionUrl(id)}/messages`, { text });
}

/** Nudge an idle orchestrator: re-arms /goal and asks it to re-check the artifacts. 202 -> the recorded user event. */
export function resumeSession(id: string, note = ""): Promise<SessionEvent> {
  return postJson<SessionEvent>(`${sessionUrl(id)}/resume`, note ? { note } : {});
}

export function interruptSession(id: string): Promise<SessionRecord> {
  return postJson<SessionRecord>(`${sessionUrl(id)}/interrupt`, {});
}

export function stopSession(id: string): Promise<SessionRecord> {
  return postJson<SessionRecord>(`${sessionUrl(id)}/stop`, {});
}

/** Poll a JSON endpoint. Returns latest data, error and a manual refresh. */
export function usePolled<T>(url: string | null, intervalMs = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!url) {
      setData(null);
      return;
    }
    let alive = true;
    const load = () =>
      getJson<T>(url)
        .then((d) => {
          if (!alive) return;
          setData(d);
          setError(null);
        })
        .catch((e: Error) => alive && setError(e.message));
    load();
    const id = window.setInterval(load, intervalMs);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [url, intervalMs, tick]);

  return { data, error, refresh };
}

export const useOverview = () => usePolled<Overview>("/api/overview");
export const useRun = (runId: string | null) => usePolled<RunDetail>(runId ? `/api/runs/${encodeURIComponent(runId)}` : null);
export const useNode = (runId: string | null, nodeId: string | null) =>
  usePolled<NodeDetail>(runId && nodeId ? `/api/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}` : null);

export const useSession = (id: string | null) => usePolled<SessionDetail>(id ? sessionUrl(id) : null);

/** Fetch a text file from inside a run via /api/runs/<id>/files/<path>. */
export function useRunFile(runId: string | null, path: string | null) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setText(null);
    setError(null);
    if (!runId || !path) return;
    let alive = true;
    const url = `/api/runs/${encodeURIComponent(runId)}/files/${path.split("/").map(encodeURIComponent).join("/")}`;
    fetch(url, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.text();
      })
      .then((t) => alive && setText(t))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [runId, path]);
  return { text, error };
}

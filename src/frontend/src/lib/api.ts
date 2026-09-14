import { useCallback, useEffect, useState } from "react";
import type { NodeDetail, Overview, RunDetail } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
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

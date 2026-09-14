export function relTime(iso: string | number | null | undefined): string {
  if (!iso) return "—";
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function fmtDate(d = new Date()): string {
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

/** First numeric metric, rendered compactly. */
export function primaryMetric(metrics: Record<string, unknown> | null | undefined, prefer?: string | null): { key: string; value: string } | null {
  const entries = Object.entries(metrics ?? {});
  const pick = (prefer && entries.find(([k]) => k === prefer)) || entries.find(([, v]) => typeof v === "number");
  if (!pick) return null;
  const [key, v] = pick;
  const num = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(num)) return { key, value: String(v) };
  const value = num >= 0 && num <= 1 ? `${(num * 100).toFixed(1)}%` : num.toFixed(3);
  return { key, value };
}

/* Status vocabulary (docs/SCHEMA.md): a node or work item is terminal when its status is one
   of the six work terminal tokens; any other lowercase word means it is live. The graph
   still needs a small set of animations, so a few conventional live words get their own
   kind and everything else live falls back to "experimenting". */

export const TERMINAL = new Set(["completed", "cancelled", "failed", "abandoned", "accepted", "rejected"]);

export function isTerminal(status: string | null | undefined): boolean {
  return !!status && TERMINAL.has(status.toLowerCase());
}

export function tone(status: string | null | undefined): "lime" | "pink" | "orange" | "neutral" | "ink" {
  const s = status?.toLowerCase();
  switch (s) {
    case "accepted":
    case "success":
    case "complete":
    case "completed":
    case "ready":
      return "lime";
    case "running":
    case "active":
      return "lime";
    case "planned":
    case "queued":
    case "pending":
      return "pink";
    case "blocked":
    case "exhausted":
    case "cancelled":
    case "failed":
    case "rejected":
    case "abandoned":
    case "revising":
    case "repairing":
      return "orange";
    default:
      return "neutral";
  }
}

/** What the graph should animate for a node status. */
export type StatusKind = "queued" | "implementing" | "experimenting" | "revising" | "candidate" | "accepted" | "dead" | "unknown";

export function statusKind(status: string | null | undefined): StatusKind {
  if (!status) return "unknown";
  const s = status.toLowerCase();
  if (s === "accepted") return "accepted";
  if (TERMINAL.has(s)) return "dead";
  switch (s) {
    case "planned":
    case "queued":
    case "pending":
      return "queued";
    case "implementing":
    case "planning":
      return "implementing";
    case "revising":
    case "repairing":
    case "blocked":
      return "revising";
    case "candidate":
    case "validating":
      return "candidate";
    default:
      return "experimenting";
  }
}

export function fmtTime(iso: string | number | null | undefined): string {
  if (!iso) return "—";
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  return new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

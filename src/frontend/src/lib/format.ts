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
export function primaryMetric(metrics: Record<string, unknown>, prefer?: string | null): { key: string; value: string } | null {
  const entries = Object.entries(metrics ?? {});
  const pick = (prefer && entries.find(([k]) => k === prefer)) || entries.find(([, v]) => typeof v === "number");
  if (!pick) return null;
  const [key, v] = pick;
  const num = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(num)) return { key, value: String(v) };
  const value = num >= 0 && num <= 1 ? `${(num * 100).toFixed(1)}%` : num.toFixed(3);
  return { key, value };
}

export function tone(status: string | null | undefined): "lime" | "pink" | "orange" | "neutral" | "ink" {
  switch (statusKind(status)) {
    case "accepted":
    case "experimenting":
    case "candidate":
      return "lime";
    case "revising":
    case "dead":
      return "orange";
    case "queued":
    case "implementing":
      return "pink";
    default:
      switch (status) {
        case "running":
        case "complete":
        case "completed":
        case "success":
          return "lime";
        case "exhausted":
        case "cancelled":
        case "blocked":
          return "orange";
        default:
          return "neutral";
      }
  }
}

/** What an agent is doing to a node, collapsed to the animation the graph draws. */
export type StatusKind = "queued" | "implementing" | "experimenting" | "revising" | "candidate" | "accepted" | "dead" | "unknown";

export function statusKind(status: string | null | undefined): StatusKind {
  switch (status) {
    case "planned":
    case "pending":
    case "queued":
      return "queued";
    case "implementing":
      return "implementing";
    case "running":
    case "experimenting":
    case "validating":
      return "experimenting";
    case "buggy":
    case "repairing":
    case "revising":
      return "revising";
    case "candidate":
      return "candidate";
    case "accepted":
      return "accepted";
    case "rejected":
    case "invalid":
    case "failed":
    case "abandoned":
    case "cancelled":
      return "dead";
    default:
      return "unknown";
  }
}

export function fmtTime(iso: string | number | null | undefined): string {
  if (!iso) return "—";
  const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  return new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

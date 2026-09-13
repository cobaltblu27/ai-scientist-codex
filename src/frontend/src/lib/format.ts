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
  switch (status) {
    case "running":
    case "accepted":
    case "complete":
      return "lime";
    case "blocked_manual_recovery":
    case "failed":
    case "rejected":
    case "cancelled":
      return "orange";
    case "pending":
    case "queued":
      return "pink";
    default:
      return "neutral";
  }
}

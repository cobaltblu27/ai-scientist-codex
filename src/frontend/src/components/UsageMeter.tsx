import type { RateLimitWindow } from "../lib/types";
import { fmtPercent, untilTime, windowLabel } from "../lib/format";

/** Subscription usage per rate-limit window, from the CLI's rate_limit events. */
export function UsageMeter({ limits, compact = false }: { limits: Record<string, RateLimitWindow> | null | undefined; compact?: boolean }) {
  const windows = Object.values(limits ?? {}).sort((a, b) => a.type.localeCompare(b.type));
  if (windows.length === 0) {
    return compact ? null : <div className="muted usage">usage: not reported yet</div>;
  }
  return (
    <div className={`usage ${compact ? "compact" : ""}`}>
      {!compact && <span className="muted">usage:</span>}
      {windows.map((w) => {
        const reset = untilTime(w.resets_at);
        const title = `${w.type}: ${w.status}${reset ? `, resets ${reset}` : ""}`;
        return (
          <span key={w.type} className={`pill tiny ${usageTone(w)}`} title={title}>
            {windowLabel(w.type)} {fmtPercent(w.utilization)}
          </span>
        );
      })}
    </div>
  );
}

/** Highest utilization across the plan windows (5h, 7d), for a headline number; overage windows only when nothing else reports. */
export function peakUsage(limits: Record<string, RateLimitWindow> | null | undefined): RateLimitWindow | null {
  const windows = Object.values(limits ?? {}).filter((w) => w.utilization != null);
  const plan = windows.filter((w) => !w.type.includes("overage"));
  let peak: RateLimitWindow | null = null;
  for (const w of plan.length > 0 ? plan : windows) {
    if (peak == null || (w.utilization ?? 0) > (peak.utilization ?? 0)) peak = w;
  }
  return peak;
}

function usageTone(w: RateLimitWindow): "lime" | "pink" | "orange" {
  if (w.status === "rejected" || (w.utilization ?? 0) >= 0.9) return "orange";
  if (w.status === "allowed_warning" || (w.utilization ?? 0) >= 0.7) return "pink";
  return "lime";
}

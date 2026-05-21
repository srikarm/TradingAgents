// web/components/DecisionTimeline.tsx
import type { DecisionPin } from "@/lib/types";
import { cn } from "@/lib/cn";

function pct(x: number | null): string {
  if (x === null || x === undefined) return "—";
  const sign = x >= 0 ? "+" : "";
  return `${sign}${(x * 100).toFixed(2)}%`;
}

function pctColor(x: number | null): string {
  if (x === null || x === undefined) return "text-fg-subtle";
  return x >= 0 ? "text-success" : "text-danger";
}

export default function DecisionTimeline({
  decisions,
}: {
  decisions: DecisionPin[];
}) {
  if (decisions.length === 0) {
    return (
      <p className="px-4 py-6 text-sm text-fg-muted">
        No decisions yet for this ticker.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-surface/40 backdrop-blur-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/40 text-left">
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              Date
            </th>
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              Rating
            </th>
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              Status
            </th>
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle text-right">
              Realized return
            </th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d, i) => (
            <tr
              key={`${d.trade_date}-${d.rating}-${i}`}
              className="border-b border-border/30 transition-colors last:border-0 hover:bg-surface/60"
            >
              <td className="px-4 py-2.5 font-mono text-fg-muted">{d.trade_date}</td>
              <td className="px-4 py-2.5 text-fg">{d.rating}</td>
              <td
                className={cn(
                  "px-4 py-2.5 font-mono text-xs",
                  d.status === "pending" ? "text-fg-subtle" : "text-fg-muted",
                )}
              >
                {d.status}
              </td>
              <td
                className={cn(
                  "px-4 py-2.5 text-right font-mono tabular-nums",
                  pctColor(d.raw_return),
                )}
              >
                {pct(d.raw_return)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import { TrendingUp, Target, Activity, ArrowDownToLine, Hash } from "lucide-react";
import type { PortfolioSummaryOut } from "@/lib/types";
import { cn } from "@/lib/cn";

function pct(x: number) {
  return `${(x * 100).toFixed(2)}%`;
}

function StatCard({
  label,
  value,
  Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  Icon: typeof TrendingUp;
  tone?: "neutral" | "positive" | "negative";
}) {
  return (
    <div className="group relative overflow-hidden rounded-xl border border-border/60 bg-surface/40 p-5 backdrop-blur-sm transition-colors hover:border-border hover:bg-surface/70">
      {/* Subtle glass highlight */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-fg/10 to-transparent"
        aria-hidden
      />
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-fg-subtle">
          {label}
        </span>
        <Icon className="h-3.5 w-3.5 text-fg-subtle/60" aria-hidden />
      </div>
      <div
        className={cn(
          "mt-3 font-mono text-[28px] font-semibold leading-none tracking-tight tabular-nums",
          tone === "positive" && "text-success",
          tone === "negative" && "text-danger",
          tone === "neutral" && "text-fg"
        )}
      >
        {value}
      </div>
    </div>
  );
}

export default function PortfolioStats({
  summary,
}: {
  summary: PortfolioSummaryOut;
}) {
  const pnlTone = summary.cumulative_pnl > 0 ? "positive" : summary.cumulative_pnl < 0 ? "negative" : "neutral";
  return (
    <div className="mb-10 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5 animate-fade-in">
      <StatCard label="Cumulative P&L" value={pct(summary.cumulative_pnl)} Icon={TrendingUp} tone={pnlTone} />
      <StatCard label="Win rate" value={pct(summary.win_rate)} Icon={Target} />
      <StatCard label="Sharpe" value={summary.sharpe.toFixed(2)} Icon={Activity} />
      <StatCard label="Max drawdown" value={pct(summary.max_drawdown)} Icon={ArrowDownToLine} tone={summary.max_drawdown < 0 ? "negative" : "neutral"} />
      <StatCard label="Trades" value={String(summary.trade_count)} Icon={Hash} />
    </div>
  );
}

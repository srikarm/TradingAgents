import type { PortfolioSummaryOut } from "@/lib/types";

function pct(x: number) {
  return `${(x * 100).toFixed(2)}%`;
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: 16,
      border: "1px solid #e5e7eb",
      borderRadius: 8,
      minWidth: 140,
    }}>
      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

export default function PortfolioStats({ summary }: { summary: PortfolioSummaryOut }) {
  return (
    <div style={{
      display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 24,
    }}>
      <Card label="Cumulative P&L" value={pct(summary.cumulative_return)} />
      <Card label="Win rate" value={pct(summary.win_rate)} />
      <Card label="Sharpe (per-decision)" value={summary.sharpe.toFixed(2)} />
      <Card label="Max drawdown" value={pct(summary.max_drawdown)} />
      <Card label="Trades" value={String(summary.trade_count)} />
    </div>
  );
}

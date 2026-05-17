"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DecisionPin, PricePoint } from "@/lib/types";

const RATING_COLOR: Record<string, string> = {
  Buy: "#16a34a",
  Overweight: "#22c55e",
  Hold: "#9ca3af",
  Underweight: "#f97316",
  Sell: "#dc2626",
};

export default function TickerPriceChart({
  prices,
  decisions,
}: {
  prices: PricePoint[];
  decisions: DecisionPin[];
}) {
  if (prices.length === 0) {
    return (
      <div style={{ padding: 24, color: "#6b7280" }}>
        Price data unavailable for this range — showing decisions only below.
      </div>
    );
  }
  const data = prices.map((p) => ({ date: p.trade_date, close: p.close }));
  const priceByDate = new Map(prices.map((p) => [p.trade_date, p.close]));

  return (
    <ResponsiveContainer width="100%" height={360}>
      <LineChart data={data} margin={{ top: 16, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={32} />
        <YAxis tick={{ fontSize: 12 }} domain={["auto", "auto"]} />
        <Tooltip />
        <Line
          type="monotone"
          dataKey="close"
          stroke="#374151"
          strokeWidth={2}
          dot={false}
        />
        {decisions.map((d) => {
          const y = priceByDate.get(d.trade_date);
          if (y === undefined) return null;
          return (
            <ReferenceDot
              key={`${d.trade_date}-${d.rating}`}
              x={d.trade_date}
              y={y}
              r={6}
              fill={RATING_COLOR[d.rating] ?? "#9ca3af"}
              stroke="#fff"
              strokeWidth={2}
            />
          );
        })}
      </LineChart>
    </ResponsiveContainer>
  );
}

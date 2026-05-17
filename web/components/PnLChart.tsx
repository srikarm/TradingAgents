"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PnLPoint } from "@/lib/types";

export default function PnLChart({ points }: { points: PnLPoint[] }) {
  if (points.length === 0) {
    return (
      <div style={{ padding: 32, textAlign: "center", color: "#6b7280" }}>
        No resolved decisions yet — once a decision is reflected on, it will
        appear here.
      </div>
    );
  }
  const data = points.map((p) => ({
    date: p.trade_date,
    pnl: Number((p.cumulative_pnl * 100).toFixed(3)),
  }));
  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 16, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey="date" tick={{ fontSize: 12 }} />
        <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
        <Tooltip formatter={(v: number) => `${v}%`} />
        <Line
          type="monotone"
          dataKey="pnl"
          stroke="#2563eb"
          strokeWidth={2}
          dot={{ r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

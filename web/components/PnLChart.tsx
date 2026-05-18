"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { LineChart as LineChartIcon } from "lucide-react";
import type { PnLPoint } from "@/lib/types";
import EmptyState from "./EmptyState";

export default function PnLChart({ points }: { points: PnLPoint[] }) {
  if (points.length === 0) {
    return (
      <EmptyState
        icon={LineChartIcon}
        title="No resolved decisions yet"
        description="Once a decision is reflected on (return + alpha known), it appears here as a P&L point."
      />
    );
  }
  const data = points.map((p) => ({
    date: p.trade_date,
    pnl: Number((p.cumulative_pnl * 100).toFixed(3)),
  }));
  return (
    <div className="rounded-lg border border-border bg-surface p-2">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 16, right: 24, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(31 31 31)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "rgb(107 107 107)" }}
            stroke="rgb(31 31 31)"
          />
          <YAxis
            tick={{ fontSize: 11, fill: "rgb(107 107 107)" }}
            tickFormatter={(v) => `${v}%`}
            stroke="rgb(31 31 31)"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "rgb(22 22 22)",
              border: "1px solid rgb(31 31 31)",
              borderRadius: 6,
              fontSize: 12,
              color: "rgb(255 255 255)",
            }}
            labelStyle={{ color: "rgb(153 153 153)" }}
            formatter={(v: number) => [`${v}%`, "P&L"]}
          />
          <ReferenceLine y={0} stroke="rgb(82 82 91)" strokeDasharray="2 2" />
          <Line
            type="monotone"
            dataKey="pnl"
            stroke="rgb(232 52 42)"
            strokeWidth={2}
            dot={{ r: 3, fill: "rgb(232 52 42)", strokeWidth: 0 }}
            activeDot={{ r: 5, fill: "rgb(232 52 42)", stroke: "rgb(255 255 255)", strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

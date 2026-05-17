import type { DecisionPin } from "@/lib/types";

function pct(x: number | null) {
  if (x === null || x === undefined) return "—";
  const sign = x >= 0 ? "+" : "";
  return `${sign}${(x * 100).toFixed(2)}%`;
}

export default function DecisionTimeline({ decisions }: { decisions: DecisionPin[] }) {
  if (decisions.length === 0) {
    return <p style={{ color: "#6b7280" }}>No decisions yet for this ticker.</p>;
  }
  return (
    <table style={{
      width: "100%", borderCollapse: "collapse", marginTop: 16,
    }}>
      <thead>
        <tr style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>
          <th style={{ padding: 8 }}>Date</th>
          <th style={{ padding: 8 }}>Rating</th>
          <th style={{ padding: 8 }}>Status</th>
          <th style={{ padding: 8 }}>Realized return</th>
        </tr>
      </thead>
      <tbody>
        {decisions.map((d) => (
          <tr key={`${d.trade_date}-${d.rating}`}
              style={{ borderBottom: "1px solid #f3f4f6" }}>
            <td style={{ padding: 8 }}>{d.trade_date}</td>
            <td style={{ padding: 8 }}>{d.rating}</td>
            <td style={{ padding: 8, color: d.status === "pending" ? "#9ca3af" : "#374151" }}>
              {d.status}
            </td>
            <td style={{ padding: 8 }}>{pct(d.raw_return)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

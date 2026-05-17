const COLORS: Record<string, string> = {
  Buy: "#16a34a",
  Overweight: "#22c55e",
  Hold: "#6b7280",
  Underweight: "#f97316",
  Sell: "#dc2626",
};

export default function RatingBadge({ rating }: { rating: string | null }) {
  if (!rating) return <span style={{ color: "#9ca3af" }}>—</span>;
  return (
    <span
      style={{
        background: COLORS[rating] ?? "#6b7280",
        color: "#fff",
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 12,
      }}
    >
      {rating}
    </span>
  );
}

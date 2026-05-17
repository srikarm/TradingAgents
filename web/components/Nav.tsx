import Link from "next/link";

export default function Nav() {
  return (
    <nav style={{ padding: "12px 24px", borderBottom: "1px solid #e5e7eb",
                  display: "flex", gap: 16 }}>
      <strong>TradingAgents</strong>
      <Link href="/history">History</Link>
    </nav>
  );
}

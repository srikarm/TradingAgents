import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PnLChart from "@/components/PnLChart";
import PortfolioStats from "@/components/PortfolioStats";

export default async function PortfolioPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const [summary, curve] = await Promise.all([
    api.portfolioSummary(),
    api.portfolioCurve(),
  ]);
  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <h1>Portfolio</h1>
        <PortfolioStats summary={summary} />
        <h2 style={{ fontSize: 16, color: "#374151", marginBottom: 8 }}>
          Cumulative P&amp;L (per-decision)
        </h2>
        <PnLChart points={curve.points} />
        <p style={{ fontSize: 12, color: "#9ca3af", marginTop: 12 }}>
          Note: P&amp;L is per-decision, not daily mark-to-market. Sharpe is
          unannualized. See spec §5.3 caveats.
        </p>
      </main>
    </>
  );
}

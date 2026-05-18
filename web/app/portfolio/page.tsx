import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
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
      <main className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
        <PageHeader
          eyebrow="Performance"
          title="Portfolio"
          description="Per-decision P&L from every resolved analysis."
        />

        <PortfolioStats summary={summary} />

        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-subtle">
              Cumulative P&amp;L
            </h2>
            <span className="text-xs text-fg-subtle">per-decision · not mark-to-market</span>
          </div>
          <PnLChart points={curve.points} />
          <p className="mt-3 text-xs text-fg-subtle">
            Note: P&amp;L is per-decision; Sharpe is unannualized. See spec §5.3 caveats.
          </p>
        </section>
      </main>
    </>
  );
}

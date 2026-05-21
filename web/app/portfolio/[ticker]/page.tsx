// web/app/portfolio/[ticker]/page.tsx
import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import Nav from "@/components/Nav";
import TickerChartWorkspace from "@/components/TickerChartWorkspace";
import DecisionTimeline from "@/components/DecisionTimeline";
import type { TickerDetailOut } from "@/lib/types";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ interval?: string }>;
}

export default async function TickerPage({ params, searchParams }: PageProps) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const { ticker } = await params;
  const { interval: rawInterval } = await searchParams;
  const interval: "1d" | "1h" = rawInterval === "1h" ? "1h" : "1d";

  let detail: TickerDetailOut;
  try {
    detail = await api.portfolioTicker(ticker, interval);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <header className="mb-6 flex flex-wrap items-baseline gap-3 border-b border-border pb-4">
          <h1 className="font-mono text-3xl font-semibold tracking-tight text-fg">
            {detail.ticker}
          </h1>
          <span className="text-sm text-fg-muted">
            {detail.decisions.length} decision{detail.decisions.length === 1 ? "" : "s"}
          </span>
        </header>

        <section className="space-y-6">
          <TickerChartWorkspace
            bars={detail.prices}
            decisions={detail.decisions}
            ticker={detail.ticker}
            interval={interval}
            dataRangeClipped={detail.data_range_clipped}
          />

          <div>
            <h2 className="mb-3 font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">
              Decisions
            </h2>
            <DecisionTimeline decisions={detail.decisions} />
          </div>
        </section>
      </main>
    </>
  );
}

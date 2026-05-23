import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import MonitorSection from "./MonitorSection";
import QuickAddForm from "./QuickAddForm";
import WatchlistTable from "./WatchlistTable";

export const metadata = { title: "Watchlist · TradingAgents" };

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const [items, me] = await Promise.all([
    api.listWatchlist(),
    api.me(),
  ]);

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <PageHeader
          eyebrow="Tickers"
          title="Watchlist"
          description="Tickers the agentic monitor will track for buy/sell signals."
        />
        <div className="mt-6 space-y-6">
          <MonitorSection
            initial={{
              enabled: me.monitor_enabled,
              briefingTimeLocal: me.briefing_time_local,
              briefingTz: me.briefing_tz,
              nextBriefingAt: null,
            }}
            tickerCount={items.length}
            tickers={items.map((i) => i.ticker)}
          />
          <QuickAddForm />
          <WatchlistTable initialItems={items} />
        </div>
      </main>
    </>
  );
}

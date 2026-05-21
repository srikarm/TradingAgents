import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import QuickAddForm from "./QuickAddForm";
import WatchlistTable from "./WatchlistTable";

export const metadata = { title: "Watchlist · TradingAgents" };

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const items = await api.listWatchlist();

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
          <QuickAddForm />
          <WatchlistTable initialItems={items} />
        </div>
      </main>
    </>
  );
}

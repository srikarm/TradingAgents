import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import SignalsFeed from "./SignalsFeed";

export const metadata = { title: "Signals · TradingAgents" };

export default async function SignalsPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const [signals, me] = await Promise.all([
    api.signalsToday(),
    api.me(),
  ]);

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <PageHeader
          eyebrow="Daily briefing"
          title="Signals"
          description={
            signals.trade_date
              ? `What your watchlist looks like as of ${signals.trade_date}.`
              : "Auto-analyses of every watchlist ticker — once the daily Monitor is on."
          }
        />
        <div className="mt-6">
          <SignalsFeed
            initial={signals}
            monitorEnabled={me.monitor_enabled}
            tz={me.briefing_tz}
          />
        </div>
      </main>
    </>
  );
}

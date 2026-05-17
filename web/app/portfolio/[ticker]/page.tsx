import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import Nav from "@/components/Nav";
import TickerPriceChart from "@/components/TickerPriceChart";
import DecisionTimeline from "@/components/DecisionTimeline";
import type { TickerDetailOut } from "@/lib/types";

export default async function TickerPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { ticker } = await params;
  let detail: TickerDetailOut;
  try {
    detail = await api.portfolioTicker(ticker);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <h1>{detail.ticker}</h1>
        <TickerPriceChart prices={detail.prices} decisions={detail.decisions} />
        <h2 style={{ fontSize: 16, color: "#374151", marginTop: 24 }}>Decisions</h2>
        <DecisionTimeline decisions={detail.decisions} />
      </main>
    </>
  );
}

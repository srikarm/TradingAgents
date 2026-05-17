import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RatingBadge from "@/components/RatingBadge";
import ReportTabs from "@/components/ReportTabs";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { runId } = await params;
  let run;
  try {
    run = await api.getRun(runId);
  } catch {
    notFound();
  }
  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <h1 style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {run.ticker} · {run.trade_date} <RatingBadge rating={run.final_rating} />
        </h1>
        <ReportTabs sections={run.report_sections} />
      </main>
    </>
  );
}

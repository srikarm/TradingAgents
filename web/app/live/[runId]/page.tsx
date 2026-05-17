import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RatingBadge from "@/components/RatingBadge";
import LiveLogStream from "@/components/LiveLogStream";

export default async function LiveRunPage({
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
        <LiveLogStream runId={run.id} initialStatus={run.status} />
        {(run.status === "succeeded" || run.status === "failed") && (
          <p style={{ marginTop: 16 }}>
            <a href={`/history/${run.id}`} style={{ color: "#2563eb" }}>
              View final reports →
            </a>
          </p>
        )}
        {run.error_summary && (
          <div style={{
            marginTop: 16, padding: 12, background: "#fef2f2",
            border: "1px solid #fecaca", borderRadius: 6, color: "#7f1d1d",
          }}>
            <strong>Error:</strong> {run.error_summary}
          </div>
        )}
      </main>
    </>
  );
}

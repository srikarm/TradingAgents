import { redirect, notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, AlertCircle, Activity } from "lucide-react";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RatingBadge from "@/components/RatingBadge";
import StatusBadge from "@/components/StatusBadge";
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
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <Link
          href="/history"
          className="mb-4 inline-flex items-center gap-1 text-sm text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to history
        </Link>

        <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-border pb-4">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="font-mono text-3xl font-semibold tracking-tight text-fg">
              {run.ticker}
            </h1>
            <span className="font-mono text-base text-fg-muted tabular-nums">
              {run.trade_date}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            <RatingBadge rating={run.final_rating} />
            {(run.status === "queued" || run.status === "running") && (
              <Link
                href={`/live/${run.id}`}
                className="inline-flex h-7 items-center gap-1.5 rounded-md bg-elevated px-2.5 text-xs font-medium text-fg transition-colors hover:bg-elevated/80"
              >
                <Activity className="h-3 w-3" aria-hidden />
                Watch live
              </Link>
            )}
          </div>
        </div>

        {run.error_summary && (
          <div
            role="alert"
            className="mb-6 flex items-start gap-3 rounded-md border border-danger/30 bg-danger/5 p-3 text-sm"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" aria-hidden />
            <div className="min-w-0">
              <div className="font-semibold text-danger">Error</div>
              <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs text-fg-muted">
                {run.error_summary}
              </pre>
            </div>
          </div>
        )}

        <ReportTabs sections={run.report_sections} />
      </main>
    </>
  );
}

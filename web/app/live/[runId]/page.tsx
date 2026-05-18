import { redirect, notFound } from "next/navigation";
import Link from "next/link";
import { AlertCircle, ArrowRight, FileText } from "lucide-react";
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

  const isTerminal = run.status === "succeeded" || run.status === "failed";

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
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
            <RatingBadge rating={run.final_rating} />
          </div>
        </div>

        <LiveLogStream runId={run.id} initialStatus={run.status} />

        {isTerminal && (
          <Link
            href={`/history/${run.id}`}
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-brand transition-colors hover:text-brand/80"
          >
            <FileText className="h-4 w-4" aria-hidden />
            View final reports
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        )}

        {run.error_summary && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-3 rounded-md border border-danger/30 bg-danger/5 p-3 text-sm animate-fade-in"
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
      </main>
    </>
  );
}

import { redirect } from "next/navigation";
import Link from "next/link";
import { History as HistoryIcon, PlayCircle, Search } from "lucide-react";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import RunCard from "@/components/RunCard";
import EmptyState from "@/components/EmptyState";

export default async function HistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { ticker } = await searchParams;
  const { items } = await api.listRuns(ticker);

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <PageHeader
          eyebrow="Runs"
          title="History"
          description="Every analysis you've launched, newest first."
          actions={
            <Link
              href="/launch"
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/60 bg-surface/60 px-3.5 text-[13px] font-medium text-fg backdrop-blur-sm transition-colors hover:border-border hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
            >
              <PlayCircle className="h-4 w-4 text-brand" aria-hidden />
              New analysis
            </Link>
          }
        />

        <form className="mb-6 flex gap-2">
          <div className="relative max-w-sm flex-1">
            <Search
              className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle"
              aria-hidden
            />
            <input
              name="ticker"
              defaultValue={ticker ?? ""}
              placeholder="Filter by ticker"
              className="h-10 w-full rounded-lg border border-border/60 bg-surface/40 pl-10 pr-3 text-sm text-fg placeholder:text-fg-subtle/70 backdrop-blur-sm transition-colors focus:border-brand/60 focus:bg-surface/60 focus:outline-none focus:ring-1 focus:ring-brand/40"
            />
          </div>
        </form>

        {items.length === 0 ? (
          <EmptyState
            icon={HistoryIcon}
            title={ticker ? `No runs for ${ticker}` : "No runs yet"}
            description={
              ticker
                ? "Try a different ticker, or launch a new analysis."
                : "Launch your first analysis to see it appear here."
            }
            action={
              <Link
                href="/launch"
                className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-gradient-to-b from-brand to-[rgb(192,40,32)] px-5 text-sm font-semibold text-brand-fg shadow-[0_1px_0_0_rgba(255,255,255,0.12)_inset,0_8px_24px_-8px_rgb(var(--brand)/0.5)] transition-all hover:from-[rgb(255,80,72)] hover:to-brand"
              >
                <PlayCircle className="h-4 w-4" aria-hidden />
                Launch analysis
              </Link>
            }
          />
        ) : (
          <div className="flex flex-col gap-2 animate-fade-in">
            {items.map((r) => (
              <RunCard key={r.id} run={r} />
            ))}
          </div>
        )}
      </main>
    </>
  );
}

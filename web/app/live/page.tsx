import { redirect } from "next/navigation";
import Link from "next/link";
import { Activity, PlayCircle } from "lucide-react";
// Link is still used for the page-header action + EmptyState action below.
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import RunCard from "@/components/RunCard";
import EmptyState from "@/components/EmptyState";

export default async function LivePage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { items } = await api.listRuns();
  const active = items.filter((r) => r.status === "queued" || r.status === "running");
  const recent = items
    .filter((r) => r.status === "succeeded" || r.status === "failed")
    .slice(0, 10);

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <PageHeader
          eyebrow="Real-time"
          title="Live runs"
          description="Active analyses + the last 10 completions."
          actions={
            <Link
              href="/launch"
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/60 bg-surface/60 px-3.5 text-[13px] font-medium text-fg backdrop-blur-sm transition-colors hover:border-border hover:bg-elevated"
            >
              <PlayCircle className="h-4 w-4 text-brand" aria-hidden />
              New analysis
            </Link>
          }
        />

        <section className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-fg-muted">
              <span className="inline-block h-2 w-2 animate-pulse-soft rounded-full bg-success" aria-hidden />
              Active
              <span className="rounded-full bg-elevated px-2 py-0.5 text-xs font-medium text-fg-muted normal-case tracking-normal">
                {active.length}
              </span>
            </h2>
          </div>
          {active.length === 0 ? (
            <EmptyState
              icon={Activity}
              title="Nothing running"
              description="Launch an analysis to watch it stream here in real time."
              action={
                <Link
                  href="/launch"
                  className="inline-flex h-9 items-center gap-1.5 rounded-md bg-brand px-4 text-sm font-medium text-brand-fg transition-colors hover:bg-brand/90"
                >
                  <PlayCircle className="h-4 w-4" aria-hidden />
                  Launch analysis
                </Link>
              }
            />
          ) : (
            <div className="flex flex-col gap-2 animate-fade-in">
              {active.map((r) => (
                // RunCard renders its own <Link>; we override the href so the
                // card navigates to /live/{id} for in-progress runs instead
                // of /history/{id}. Wrapping the card in another <Link> here
                // produced nested <a> tags (invalid HTML, broken keyboard
                // nav, React hydration warning).
                <RunCard key={r.id} run={r} href={`/live/${r.id}`} />
              ))}
            </div>
          )}
        </section>

        {recent.length > 0 && (
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-fg-muted">
              Recent
            </h2>
            <div className="flex flex-col gap-2 animate-fade-in">
              {recent.map((r) => (
                <RunCard key={r.id} run={r} />
              ))}
            </div>
          </section>
        )}
      </main>
    </>
  );
}

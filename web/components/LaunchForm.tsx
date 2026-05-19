"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, Loader2, Play, ArrowRight } from "lucide-react";
import { launchRunAction, type LaunchFormError } from "@/app/launch/actions";
import { cn } from "@/lib/cn";

const ANALYSTS = [
  { key: "market", label: "Market", hint: "Price action, technical indicators" },
  { key: "social", label: "Social", hint: "Sentiment from social signals" },
  { key: "news", label: "News", hint: "Recent news + insider transactions" },
  { key: "fundamentals", label: "Fundamentals", hint: "Balance sheet, cashflow, income" },
] as const;

/** Section card matches the rhythm of /history rows and /portfolio stat cards:
 * glass surface, soft border, top hairline highlight, generous padding. The
 * form is composed of these section cards (Symbol & Date, Analysts) sitting
 * inside the same max-w-7xl container the other pages use. */
function SectionCard({
  eyebrow,
  description,
  children,
}: {
  eyebrow: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="relative overflow-hidden rounded-xl border border-border/60 bg-surface/40 p-6 backdrop-blur-sm sm:p-7">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-fg/10 to-transparent"
        aria-hidden
      />
      <div className="mb-5 flex items-baseline justify-between gap-4">
        <h2 className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-subtle">
          {eyebrow}
        </h2>
        {description && (
          <p className="text-xs text-fg-subtle">{description}</p>
        )}
      </div>
      {children}
    </section>
  );
}

export default function LaunchForm() {
  const [error, setError] = useState<LaunchFormError | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  const onSubmit = (fd: FormData) => {
    setError(null);
    startTransition(async () => {
      const res = await launchRunAction(fd);
      if (res) setError(res);
    });
  };

  return (
    <form action={onSubmit} className="grid gap-4">
      <SectionCard
        eyebrow="Symbol & date"
        description="The ticker the analysts evaluate, and the reference date."
      >
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <label
              htmlFor="ticker"
              className="mb-2 block text-[11px] font-medium uppercase tracking-[0.14em] text-fg-muted"
            >
              Ticker
            </label>
            <input
              id="ticker"
              name="ticker"
              required
              maxLength={12}
              placeholder="NVDA"
              autoComplete="off"
              autoCapitalize="characters"
              className="h-11 w-full rounded-lg border border-border/60 bg-bg/40 px-3.5 font-mono text-[15px] text-fg placeholder:text-fg-subtle/60 transition-colors focus:border-brand/60 focus:bg-bg/70 focus:outline-none focus:ring-1 focus:ring-brand/40"
            />
            <p className="mt-2 text-xs text-fg-subtle">
              US listing or supported foreign suffix — e.g.{" "}
              <span className="font-mono text-fg-muted">NVDA</span>,{" "}
              <span className="font-mono text-fg-muted">7203.T</span> (Tokyo),{" "}
              <span className="font-mono text-fg-muted">BBCA.JK</span> (Jakarta).
            </p>
          </div>

          <div>
            <label
              htmlFor="trade_date"
              className="mb-2 block text-[11px] font-medium uppercase tracking-[0.14em] text-fg-muted"
            >
              Trade date
            </label>
            <input
              id="trade_date"
              name="trade_date"
              type="date"
              required
              className="h-11 w-full rounded-lg border border-border/60 bg-bg/40 px-3.5 font-mono text-[15px] text-fg transition-colors focus:border-brand/60 focus:bg-bg/70 focus:outline-none focus:ring-1 focus:ring-brand/40 [color-scheme:dark]"
            />
            <p className="mt-2 text-xs text-fg-subtle">
              Past trading day; the analysts evaluate against this date.
            </p>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        eyebrow="Analysts"
        description="All four run by default. Disable any you don't want."
      >
        {/* 4-up at lg+ (one row across the wide card), 2-up at sm-md,
         * stacked on mobile. Echoes the 5-up stat grid on /portfolio. */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {ANALYSTS.map((a) => (
            <label
              key={a.key}
              className="group relative flex cursor-pointer items-start gap-3 rounded-lg border border-border/40 bg-bg/30 p-4 transition-all hover:border-border hover:bg-bg/50 has-[:checked]:border-brand/35 has-[:checked]:bg-brand/[0.04]"
            >
              <input
                type="checkbox"
                name="analysts"
                value={a.key}
                defaultChecked
                className="mt-0.5 h-4 w-4 cursor-pointer rounded border-border bg-surface accent-brand focus:ring-1 focus:ring-brand focus:ring-offset-0"
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-fg">{a.label}</div>
                <div className="mt-1 text-xs leading-relaxed text-fg-subtle">
                  {a.hint}
                </div>
              </div>
            </label>
          ))}
        </div>
      </SectionCard>

      {/* Action bar — right-aligned button + inline error left of it.
       * Matches the "action rail" pattern of /history's header actions. */}
      <div className="mt-2 flex flex-col-reverse items-stretch justify-end gap-3 sm:flex-row sm:items-center">
        {error && (
          <div
            role="alert"
            className="flex flex-1 items-start gap-3 rounded-lg border border-danger/30 bg-danger/[0.06] px-4 py-3 text-sm text-danger animate-fade-in"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
              {error.kind === "conflict" ? (
                <>
                  <p>A run is already in progress for this ticker + date.</p>
                  <button
                    type="button"
                    onClick={() => router.push(`/live/${error.existingRunId}`)}
                    className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-fg underline-offset-2 hover:underline"
                  >
                    View running run
                    <ArrowRight className="h-3 w-3" aria-hidden />
                  </button>
                </>
              ) : (
                <p>{error.message}</p>
              )}
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={isPending}
          className={cn(
            "group relative inline-flex h-11 items-center justify-center gap-2 overflow-hidden rounded-lg px-6 text-sm font-semibold text-brand-fg transition-all sm:min-w-[200px]",
            "bg-gradient-to-b from-brand to-[rgb(192,40,32)]",
            "shadow-[0_1px_0_0_rgba(255,255,255,0.12)_inset,0_8px_24px_-8px_rgb(var(--brand)_/_0.5)]",
            "hover:from-[rgb(255,80,72)] hover:to-brand hover:shadow-[0_1px_0_0_rgba(255,255,255,0.15)_inset,0_12px_32px_-8px_rgb(var(--brand)_/_0.7)]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
            "disabled:cursor-wait disabled:opacity-60"
          )}
        >
          {isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Launching…
            </>
          ) : (
            <>
              <Play className="h-4 w-4" strokeWidth={2.5} aria-hidden />
              Launch analysis
            </>
          )}
        </button>
      </div>
    </form>
  );
}

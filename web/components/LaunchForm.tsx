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
    <form action={onSubmit} className="grid gap-7">
      {/* Ticker + date side-by-side on wider screens, stacked on mobile */}
      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label htmlFor="ticker" className="mb-2 block text-[12px] font-medium uppercase tracking-[0.14em] text-fg-subtle">
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
            className="h-11 w-full rounded-lg border border-border/60 bg-surface/40 px-3.5 font-mono text-[15px] text-fg placeholder:text-fg-subtle/60 backdrop-blur-sm transition-colors focus:border-brand/60 focus:bg-surface/60 focus:outline-none focus:ring-1 focus:ring-brand/40"
          />
          <p className="mt-2 text-xs text-fg-subtle">
            US listing or supported foreign suffix (e.g. <span className="font-mono text-fg-muted">NVDA</span>, <span className="font-mono text-fg-muted">7203.T</span>).
          </p>
        </div>

        <div>
          <label htmlFor="trade_date" className="mb-2 block text-[12px] font-medium uppercase tracking-[0.14em] text-fg-subtle">
            Trade date
          </label>
          <input
            id="trade_date"
            name="trade_date"
            type="date"
            required
            className="h-11 w-full rounded-lg border border-border/60 bg-surface/40 px-3.5 font-mono text-[15px] text-fg placeholder:text-fg-subtle backdrop-blur-sm transition-colors focus:border-brand/60 focus:bg-surface/60 focus:outline-none focus:ring-1 focus:ring-brand/40 [color-scheme:dark]"
          />
          <p className="mt-2 text-xs text-fg-subtle">
            The reference date the analysts evaluate against.
          </p>
        </div>
      </div>

      <fieldset className="rounded-xl border border-border/60 bg-surface/40 p-5 backdrop-blur-sm">
        <legend className="px-2 text-[10px] font-medium uppercase tracking-[0.18em] text-fg-subtle">
          Analysts
        </legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {ANALYSTS.map((a) => (
            <label
              key={a.key}
              className="group flex cursor-pointer items-start gap-3 rounded-lg border border-transparent p-3 transition-all hover:border-border/60 hover:bg-elevated/40 has-[:checked]:border-brand/30 has-[:checked]:bg-brand/[0.04]"
            >
              <input
                type="checkbox"
                name="analysts"
                value={a.key}
                defaultChecked
                className="mt-0.5 h-4 w-4 cursor-pointer rounded border-border bg-surface text-brand accent-brand focus:ring-1 focus:ring-brand focus:ring-offset-0"
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-fg">{a.label}</div>
                <div className="mt-0.5 text-xs leading-relaxed text-fg-subtle">{a.hint}</div>
              </div>
            </label>
          ))}
        </div>
      </fieldset>

      <button
        type="submit"
        disabled={isPending}
        className={cn(
          "group relative inline-flex h-11 items-center justify-center gap-2 overflow-hidden rounded-lg px-6 text-sm font-semibold text-brand-fg transition-all",
          "bg-gradient-to-b from-brand to-[rgb(192,40,32)]",
          "shadow-[0_1px_0_0_rgba(255,255,255,0.12)_inset,0_8px_24px_-8px_rgb(var(--brand)/0.5)]",
          "hover:from-[rgb(255,80,72)] hover:to-brand hover:shadow-[0_1px_0_0_rgba(255,255,255,0.15)_inset,0_12px_32px_-8px_rgb(var(--brand)/0.7)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
          "disabled:cursor-wait disabled:opacity-60"
        )}
      >
        {isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Launching analysis…
          </>
        ) : (
          <>
            <Play className="h-4 w-4" strokeWidth={2.5} aria-hidden />
            Launch analysis
          </>
        )}
      </button>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger animate-fade-in"
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
    </form>
  );
}

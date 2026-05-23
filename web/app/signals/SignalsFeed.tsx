"use client";
import Link from "next/link";
import { Zap } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import type { SignalListOut } from "@/lib/types";
import SignalCard from "./SignalCard";
import { isActionable } from "./ranking";

// Re-export so existing call-sites (and external tests) can import from
// SignalsFeed; the pure helper lives in ./ranking.ts because vitest can't
// transform .tsx under Next's `jsx: preserve` tsconfig.
export { isActionable };

export default function SignalsFeed({
  initial, monitorEnabled, tz,
}: {
  initial: SignalListOut;
  monitorEnabled: boolean;
  tz: string | null;
}) {
  if (!monitorEnabled) {
    return (
      <EmptyState
        icon={Zap}
        title="Daily Monitor is off"
        description="Enable the daily Monitor on /watchlist to get a fresh signal for every ticker every morning."
        action={
          <Link
            href="/watchlist"
            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-brand/60 bg-brand/10 px-4 text-sm font-medium text-brand hover:bg-brand/15"
          >
            Go to Watchlist
          </Link>
        }
      />
    );
  }

  if (initial.items.length === 0) {
    return (
      <EmptyState
        icon={Zap}
        title={`No signals yet for ${initial.trade_date ?? "today"}`}
        description={
          tz
            ? `Waiting for the next briefing run. The Monitor fires at your configured time (${tz}).`
            : "Configure a briefing time on /watchlist."
        }
        action={
          <Link
            href="/watchlist"
            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-border/60 bg-surface/40 px-4 text-sm text-fg-muted hover:text-fg"
          >
            Manage Monitor
          </Link>
        }
      />
    );
  }

  const actionable = initial.items.filter(isActionable);
  const neutral = initial.items.filter((s) => !isActionable(s));

  return (
    <div className="space-y-6">
      {actionable.length > 0 && (
        <section aria-label="Actionable signals">
          <h2 className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            Actionable · {actionable.length}
          </h2>
          <div className="flex flex-col gap-2">
            {actionable.map((s) => (
              <SignalCard key={s.run_id} signal={s} />
            ))}
          </div>
        </section>
      )}
      {neutral.length > 0 && (
        <section aria-label="Holds">
          <h2 className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            Holding pattern · {neutral.length}
          </h2>
          <div className="flex flex-col gap-2 opacity-60">
            {neutral.map((s) => (
              <SignalCard key={s.run_id} signal={s} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

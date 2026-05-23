"use client";
import Link from "next/link";
import { ArrowUp, ArrowDown, Minus, Loader2, Bookmark } from "lucide-react";
import type { SignalOut } from "@/lib/types";

export default function SignalCard({ signal }: { signal: SignalOut }) {
  const Icon =
    signal.final_rating === "BUY" ? ArrowUp :
    signal.final_rating === "SELL" ? ArrowDown :
    signal.final_rating === "HOLD" ? Minus :
    Loader2;

  const tone =
    signal.final_rating === "BUY"  ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" :
    signal.final_rating === "SELL" ? "text-rose-400 bg-rose-500/10 border-rose-500/30" :
    signal.final_rating === "HOLD" ? "text-fg-muted bg-surface/40 border-border/60" :
    "text-fg-muted bg-surface/40 border-border/60 animate-pulse";

  return (
    <Link
      href={`/history/${signal.run_id}`}
      className="group flex items-center gap-3 rounded-xl border border-border/60 bg-surface/40 px-4 py-3 backdrop-blur-sm transition-colors hover:border-border hover:bg-surface/70"
    >
      <div
        className={`flex h-8 w-16 shrink-0 items-center justify-center gap-1 rounded-md border ${tone} font-mono text-[11px] font-semibold uppercase`}
      >
        <Icon
          className={`h-3 w-3 ${!signal.final_rating ? "animate-spin" : ""}`}
          aria-hidden
        />
        {signal.final_rating ?? "…"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[15px] font-semibold text-fg">
            {signal.ticker}
          </span>
          <span className="font-mono text-[10px] text-fg-subtle">
            {new Date(signal.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        {signal.notes && (
          <p className="mt-0.5 truncate text-xs text-fg-muted">
            <Bookmark className="mr-1 inline h-2.5 w-2.5" aria-hidden />
            {signal.notes}
          </p>
        )}
      </div>
    </Link>
  );
}

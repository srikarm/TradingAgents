"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { MonitorOut } from "@/lib/types";

type MonitorState = {
  enabled: boolean;
  briefingTimeLocal: string | null;
  briefingTz: string | null;
  nextBriefingAt: string | null;
};

function browserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC";
  } catch {
    return "UTC";
  }
}

function formatCountdown(targetIso: string | null): string {
  if (!targetIso) return "";
  const ms = new Date(targetIso).getTime() - Date.now();
  if (ms <= 0) return "due now";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

export default function MonitorSection({
  initial,
  tickerCount,
  tickers,
}: {
  initial: MonitorState;
  tickerCount: number;
  tickers: string[];
}) {
  const router = useRouter();
  const [state, setState] = useState<MonitorState>(initial);
  const [countdown, setCountdown] = useState(() => formatCountdown(initial.nextBriefingAt));
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const tick = () => setCountdown(formatCountdown(state.nextBriefingAt));
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, [state.nextBriefingAt]);

  async function apply(next: Partial<MonitorState>) {
    const merged = { ...state, ...next };
    setState(merged);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.updateMonitor({
          enabled: merged.enabled,
          briefing_time_local: merged.briefingTimeLocal,
          briefing_tz: merged.briefingTz,
        });
        setState({
          enabled: res.enabled,
          briefingTimeLocal: res.briefing_time_local,
          briefingTz: res.briefing_tz,
          nextBriefingAt: res.next_briefing_at,
        });
      } catch (e) {
        console.error("monitor save failed", e);
      }
    }, 800);
  }

  async function onEnable() {
    const tz = state.briefingTz ?? browserTz();
    const time = state.briefingTimeLocal ?? "07:00";
    // Immediate POST so the user is "on" right away — bypass the 800ms debounce.
    try {
      const res = await api.updateMonitor({
        enabled: true, briefing_time_local: time, briefing_tz: tz,
      });
      setState({
        enabled: true,
        briefingTimeLocal: res.briefing_time_local,
        briefingTz: res.briefing_tz,
        nextBriefingAt: res.next_briefing_at,
      });
    } catch (e) {
      console.error("monitor enable failed", e);
    }
  }

  async function onDisable() {
    try {
      const res = await api.updateMonitor({ enabled: false });
      setState((s) => ({
        ...s,
        enabled: false,
        briefingTimeLocal: res.briefing_time_local,
        briefingTz: res.briefing_tz,
        nextBriefingAt: null,
      }));
    } catch (e) {
      console.error("monitor disable failed", e);
    }
  }

  // STATE A — monitor off
  if (!state.enabled) {
    const subtitle = tickerCount > 0
      ? `Auto-analyze your ${tickerCount} ${tickerCount === 1 ? "ticker" : "tickers"} once a day.`
      : "Add tickers above, then enable to auto-analyze them daily.";
    return (
      <div className="rounded-xl border border-border/60 bg-surface/40 p-4 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Sparkles className="h-4 w-4 text-fg-subtle" aria-hidden />
            <span className="text-sm font-medium text-fg">Daily monitor</span>
          </div>
          <button
            type="button"
            onClick={onEnable}
            disabled={tickerCount === 0}
            className="inline-flex h-8 items-center rounded-lg border border-brand/60 bg-brand/10 px-3 text-xs font-medium text-brand transition-colors hover:bg-brand/15 disabled:opacity-50"
          >
            Enable
          </button>
        </div>
        <p className="mt-1.5 text-xs text-fg-muted">{subtitle}</p>
      </div>
    );
  }

  // STATE B — monitor on
  const tickerSummary = tickers.length
    ? `we analyze ${tickerCount} ticker${tickerCount === 1 ? "" : "s"}` +
      (tickerCount > 0 ? ` (${tickers.slice(0, 3).join(", ")}${tickerCount > 3 ? ", …" : ""})` : "")
    : "no tickers on the watchlist yet";
  return (
    <div className="rounded-xl border border-brand/40 bg-surface/40 p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Sparkles className="h-4 w-4 text-brand" aria-hidden />
          <span className="text-sm font-medium text-fg">Daily monitor</span>
        </div>
        <span className="font-mono text-[11px] text-fg-subtle">
          Next briefing: {countdown}
        </span>
      </div>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-col gap-1 text-xs text-fg-subtle">
          Time
          <input
            type="time"
            value={state.briefingTimeLocal ?? "07:00"}
            onChange={(e) => apply({ briefingTimeLocal: e.target.value })}
            aria-label="Briefing time"
            className="h-9 w-32 rounded-lg border border-border/60 bg-surface/40 px-2 font-mono text-sm text-fg focus:border-brand/60 focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-fg-subtle">
          Timezone
          <input
            type="text"
            list="iana-tz-list"
            value={state.briefingTz ?? browserTz()}
            onChange={(e) => apply({ briefingTz: e.target.value })}
            aria-label="Timezone"
            className="h-9 w-56 rounded-lg border border-border/60 bg-surface/40 px-2 font-mono text-sm text-fg focus:border-brand/60 focus:outline-none"
          />
        </label>
        <button
          type="button"
          onClick={onDisable}
          className="h-9 rounded-lg border border-border/60 bg-surface/40 px-3 text-xs text-fg-muted hover:text-fg sm:ml-auto"
        >
          Disable
        </button>
      </div>
      <p className="mt-2 text-xs text-fg-muted">
        At {state.briefingTimeLocal} {state.briefingTz} each day, {tickerSummary}.
      </p>
    </div>
  );
}

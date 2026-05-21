// web/components/TickerChartWorkspace.tsx
"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  LineStyle,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { OHLCVBar, DecisionPin } from "@/lib/types";
import { ema, rsi, sma } from "./TickerChartWorkspace.indicators";
import { cn } from "@/lib/cn";

interface Props {
  bars: OHLCVBar[];
  decisions: DecisionPin[];
  ticker: string;
  interval: "1d" | "1h";
  dataRangeClipped?: boolean;
}

const RATING_COLOR: Record<string, string> = {
  Buy: "#16a34a",
  Overweight: "#22c55e",
  Hold: "#9ca3af",
  Underweight: "#f97316",
  Sell: "#dc2626",
};

/** Convert a trade_date string to lightweight-charts Time.
 *  - "YYYY-MM-DD" -> business-day string (daily)
 *  - "YYYY-MM-DDTHH:MM:SSZ" -> unix seconds (intraday) */
function toLwcTime(tradeDate: string): Time {
  if (tradeDate.includes("T")) {
    return Math.floor(new Date(tradeDate).getTime() / 1000) as UTCTimestamp;
  }
  return tradeDate as Time;
}

function fmtPct(x: number): string {
  const sign = x >= 0 ? "+" : "";
  return `${sign}${(x * 100).toFixed(1)}%`;
}

export default function TickerChartWorkspace({
  bars,
  decisions,
  ticker,
  interval,
  dataRangeClipped,
}: Props) {
  const priceContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!priceContainerRef.current || !rsiContainerRef.current) return;
    if (bars.length === 0) return;

    const sharedLayout = {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: "rgb(156, 163, 175)",
      fontFamily: "var(--font-mono, ui-monospace, monospace)",
    };
    const sharedGrid = {
      vertLines: { color: "rgba(255,255,255,0.04)" },
      horzLines: { color: "rgba(255,255,255,0.04)" },
    };
    const sharedTime = {
      borderColor: "rgba(255,255,255,0.08)",
      timeVisible: interval === "1h",
      secondsVisible: false,
    };

    // === Main chart: candlesticks + MAs + volume ===
    const mainChart = createChart(priceContainerRef.current, {
      autoSize: true,
      layout: sharedLayout,
      grid: sharedGrid,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: sharedTime,
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
    });

    // v5 API: chart.addSeries(SeriesDefinition, options)
    const candles = mainChart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderUpColor: "#16a34a",
      borderDownColor: "#dc2626",
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });
    candles.setData(
      bars.map((b) => ({
        time: toLwcTime(b.trade_date),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );

    // v5 API: createSeriesMarkers() is a standalone function
    createSeriesMarkers(
      candles,
      decisions.map((d) => {
        const isLong = d.rating === "Buy" || d.rating === "Overweight";
        const isShort = d.rating === "Sell" || d.rating === "Underweight";
        return {
          time: toLwcTime(d.trade_date),
          position: (isLong ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
          color: RATING_COLOR[d.rating] ?? "#9ca3af",
          shape: (isLong ? "arrowUp" : isShort ? "arrowDown" : "circle") as
            | "arrowUp"
            | "arrowDown"
            | "circle",
          text: d.raw_return != null ? `${d.rating} ${fmtPct(d.raw_return)}` : d.rating,
        };
      }),
    );

    // Moving average overlays on the price pane.
    const overlays: Array<{
      fn: typeof sma;
      period: number;
      color: string;
      title: string;
    }> = [
      { fn: sma, period: 20, color: "#3A7BD5", title: "SMA(20)" },
      { fn: sma, period: 50, color: "#7C3AED", title: "SMA(50)" },
      { fn: ema, period: 9, color: "#E8342A", title: "EMA(9)" },
      { fn: ema, period: 21, color: "#F59E0B", title: "EMA(21)" },
    ];
    for (const { fn, period, color, title } of overlays) {
      const line = mainChart.addSeries(LineSeries, { color, lineWidth: 1, title });
      line.setData(fn(bars, period).map((p) => ({ time: toLwcTime(p.time), value: p.value })));
    }

    // Volume histogram in the same chart, bottom 30%.
    const volumeSeries = mainChart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: "rgba(255,255,255,0.3)",
    });
    mainChart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    });
    volumeSeries.setData(
      bars.map((b) => ({
        time: toLwcTime(b.trade_date),
        value: b.volume,
        color:
          b.close >= b.open ? "rgba(22,163,74,0.5)" : "rgba(220,38,38,0.5)",
      })),
    );

    // === RSI chart: separate IChartApi, synchronized time scale ===
    const rsiChart = createChart(rsiContainerRef.current, {
      autoSize: true,
      layout: sharedLayout,
      grid: sharedGrid,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { ...sharedTime, visible: false },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
    });
    const rsiSeries = rsiChart.addSeries(LineSeries, {
      color: "#3A7BD5",
      lineWidth: 1,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    rsiSeries.setData(
      rsi(bars, 14).map((p) => ({ time: toLwcTime(p.time), value: p.value })),
    );
    rsiSeries.createPriceLine({
      price: 70,
      color: "rgba(220,38,38,0.4)",
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: false,
      title: "",
    });
    rsiSeries.createPriceLine({
      price: 30,
      color: "rgba(22,163,74,0.4)",
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: false,
      title: "",
    });

    // Synchronize time scale between main chart and RSI chart.
    // In v5, subscribeVisibleLogicalRangeChange returns void; save handlers for cleanup.
    const mainToRsiHandler = (range: import("lightweight-charts").LogicalRange | null) => {
      if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
    };
    const rsiToMainHandler = (range: import("lightweight-charts").LogicalRange | null) => {
      if (range) mainChart.timeScale().setVisibleLogicalRange(range);
    };
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(mainToRsiHandler);
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange(rsiToMainHandler);

    mainChart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();

    return () => {
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(mainToRsiHandler);
      rsiChart.timeScale().unsubscribeVisibleLogicalRangeChange(rsiToMainHandler);
      mainChart.remove();
      rsiChart.remove();
    };
  }, [bars, decisions, interval]);

  function handleIntervalChange(next: "1d" | "1h") {
    const url = new URL(window.location.href);
    if (next === "1d") {
      url.searchParams.delete("interval");
    } else {
      url.searchParams.set("interval", next);
    }
    router.replace(url.pathname + url.search);
  }

  if (bars.length === 0) {
    return (
      <div className="rounded-xl border border-border/60 bg-surface/40 p-6 text-sm text-fg-muted backdrop-blur-sm">
        Price data unavailable for this range — showing decisions below only.
      </div>
    );
  }

  return (
    <div
      data-testid="ticker-chart-workspace"
      className="overflow-hidden rounded-xl border border-border/60 bg-surface/40 backdrop-blur-sm"
    >
      <header className="flex items-center justify-between border-b border-border/40 px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h2 className="font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">
            {ticker}
          </h2>
          <span className="text-[11px] text-fg-subtle">
            candles · sma(20,50) · ema(9,21) · volume · rsi(14)
          </span>
        </div>
        <div
          role="tablist"
          aria-label="Chart interval"
          className="inline-flex items-center rounded-md border border-border/60 bg-surface/40"
        >
          <button
            type="button"
            role="tab"
            aria-selected={interval === "1d"}
            onClick={() => handleIntervalChange("1d")}
            className={cn(
              "px-2.5 py-1 text-xs transition-colors",
              interval === "1d"
                ? "rounded-md bg-elevated text-fg"
                : "text-fg-muted hover:text-fg",
            )}
          >
            1D
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={interval === "1h"}
            onClick={() => handleIntervalChange("1h")}
            className={cn(
              "px-2.5 py-1 text-xs transition-colors",
              interval === "1h"
                ? "rounded-md bg-elevated text-fg"
                : "text-fg-muted hover:text-fg",
            )}
          >
            1H
          </button>
        </div>
      </header>
      {dataRangeClipped && (
        <p className="border-b border-amber-500/20 bg-amber-500/5 px-4 py-2 text-xs text-amber-200/80">
          Hourly data limited to the last 60 days by the upstream provider.
        </p>
      )}
      <div ref={priceContainerRef} className="h-[420px]" />
      <div ref={rsiContainerRef} className="h-[120px] border-t border-border/40" />
    </div>
  );
}

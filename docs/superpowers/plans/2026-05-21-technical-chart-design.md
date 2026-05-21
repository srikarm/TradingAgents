# Design: Technical chart for `/portfolio/[ticker]` (Wave 4 item 3)

**Date:** 2026-05-21
**Status:** Approved (design) — implementation plan to follow
**Owner:** erikgunawans
**Related:** Wave 4 item 3. Builds on PRs #22 (auth UI) and #23 (realtime opt-in). The PR #16 scope-note about "TickerPriceChart + DecisionTimeline still have legacy inline styles" is finally addressed here.

---

## 1. Context

The current price chart on `/portfolio/[ticker]` is `web/components/TickerPriceChart.tsx` — a Recharts `<LineChart>` showing daily CLOSE prices with decision-rating dots overlaid as `<ReferenceDot>` markers. Below it is `web/components/DecisionTimeline.tsx`, a plain HTML `<table>` listing each decision's date, rating, status, and realized return %. Both components have inline styles (e.g., `style={{ padding: 24, color: "#6b7280" }}`) — they predate the PR #16 Axiara design-token migration and look out of place on the rest of the dashboard.

The user's framing: *"technical and price Chart is shown properly so technical trader gain insightful information."* A line chart of daily closes plus a table is the bare minimum — it doesn't surface OHLC structure, volume context, trend direction, or momentum. A technical trader looking at TradingAgents's analyses would want at least: candlesticks, volume, moving averages, an RSI-style momentum indicator, and the ability to zoom into intraday timeframes.

## 2. Goals

- Replace `TickerPriceChart` with a proper candlestick chart using TradingView **lightweight-charts** (purpose-built for financial visualization, used by TradingView itself for embeds).
- Show 4 indicators in v1: **Volume** histogram, **SMA(20, 50)** + **EMA(9, 21)** as price-pane overlays, and **RSI(14)** in a separate pane with 30/70 reference lines.
- Add a **Daily / Hourly** timeframe toggle (yfinance's free-tier supports both; hourly limited to last 60 days).
- Mark each TradingAgents decision (Buy/Hold/Sell + realized return) as an **arrow marker on the price pane** AND keep `DecisionTimeline` as a tabular view below, restyled with Axiara tokens.
- Server-side, widen `PricePoint` to `OHLCVBar` (open/high/low/close/volume) and accept an `interval` query param.
- All visuals match the existing Axiara dark theme (brand-red + brand-blue accents, glass surfaces, JetBrains Mono labels).

## 3. Non-goals

- Drawing tools (trend lines, Fibonacci retracements, manual annotations) — TradingView's flagship feature; out of scope for this PR.
- Additional indicators beyond Volume + SMA + EMA + RSI (Bollinger Bands, MACD, Stochastic) — all easy additive follow-ups.
- Per-user chart layout persistence (saved indicator toggles, custom periods) — would need DB schema; out of scope.
- Minute-level bars — yfinance free supports it for last 30 days, but TradingAgents's position-trading focus doesn't justify the extra UI surface.
- Real-time streaming price updates — would need a different data source than yfinance + WebSocket plumbing.
- Multi-ticker overlay / comparison — single ticker per chart.
- `PnLChart` redesign (portfolio-level P&L curve) — a different component on `/portfolio/` (not `/portfolio/[ticker]`); same library could be applied later but not bundled in this PR.

## 4. Architecture

Three logical surface changes:

1. **Server**: widen `PricePoint` schema to `OHLCVBar` (open/high/low/close/volume). `price_cache.fetch_prices(...)` accepts `interval: Literal["1d", "1h"]`. `/portfolio/ticker/{ticker}` accepts `?interval=1h`. Cache key includes interval so daily and hourly are cached separately.

2. **Web component**: new `TickerChartWorkspace` client component wraps lightweight-charts via React refs. Computes SMA/EMA/RSI client-side from OHLCV input via pure-function math (`web/components/TickerChartWorkspace.indicators.ts`). Renders three visual panes: candlestick + moving-average overlays + decision markers; volume histogram; RSI(14) with 30/70 reference lines.

3. **Layout**: `/portfolio/[ticker]/page.tsx` replaces `<TickerPriceChart>` with `<TickerChartWorkspace>`. The interval lives in `searchParams` (`?interval=1h`) so the URL is bookmarkable and reload-stable. `DecisionTimeline` keeps its role below the chart, restyled with Tailwind + Axiara tokens (PR #16 scope item finally cleared).

```
                          ┌────────────────────────────────────────────────────┐
                          │  /portfolio/[ticker]/page.tsx (server component)   │
                          │     │                                              │
                          │     ├─► api.portfolioTicker(ticker, interval)      │
                          │     │      └─► OHLCVBar[] + DecisionPin[]          │
                          │     │                                              │
                          │     ├─► <TickerChartWorkspace>  (client)           │
                          │     │      ├── Pane 1: candlesticks + SMA + EMA   │
                          │     │      │           + decision arrow markers   │
                          │     │      ├── Pane 2: volume histogram (color-   │
                          │     │      │           coded by up/down day)      │
                          │     │      ├── Pane 3: RSI(14) + 30/70 lines      │
                          │     │      └── Toolbar: Daily | Hourly toggle     │
                          │     │                                              │
                          │     └─► <DecisionTimeline>  (restyled)            │
                          └────────────────────────────────────────────────────┘
                                          │
                                          ▼
                          ┌────────────────────────────────────────────────────┐
                          │  server/app/routers/portfolio.py                   │
                          │   GET /portfolio/ticker/{ticker}?interval=1d|1h    │
                          │     └─► price_cache.fetch_prices(ticker, ...,      │
                          │                                  interval=interval)│
                          │            └─► yfinance + 24h disk cache (per     │
                          │                interval — separate cache keys)    │
                          └────────────────────────────────────────────────────┘
```

## 5. File structure

| File | Action | Responsibility |
|---|---|---|
| `server/app/schemas/portfolio.py` | modify | Rename `PricePoint` → `OHLCVBar`; add open/high/low/volume fields. `TickerDetailOut.prices` references the new shape. |
| `server/app/services/price_cache.py` | modify | `fetch_prices(..., interval: Literal["1d", "1h"] = "1d")`. Cache key includes interval. yfinance `Ticker.history(start=..., end=..., interval=interval)` produces OHLCV. For hourly, clip to last 60 days; return `data_range_clipped: bool` flag. |
| `server/app/routers/portfolio.py` | modify | `/portfolio/ticker/{ticker}` accepts `?interval=1d\|1h`. Validates the value, passes to `fetch_prices`. |
| `web/lib/types.ts` | regenerate | OpenAPI types regenerate; `PricePoint` → `OHLCVBar`. Update any other type references. |
| `web/lib/api.ts` | modify | `portfolioTicker(ticker: string, interval?: "1d" \| "1h")` — append `?interval=...` when set. |
| `web/components/TickerChartWorkspace.tsx` | create | Client component. Wraps two stacked lightweight-charts instances (one for price+volume with synchronized panes via priceScaleId; a second for RSI) sharing a time scale via `subscribeVisibleTimeRangeChange`. Renders the timeframe toggle + indicator legend. ~250 lines. |
| `web/components/TickerChartWorkspace.indicators.ts` | create | Pure JS functions: `sma(bars, period)`, `ema(bars, period)`, `rsi(bars, period)`. ~50 lines total. |
| `web/components/TickerChartWorkspace.indicators.test.ts` | create | Vitest unit tests for the three indicator functions. Property-based: monotone input, all-same prices, edge cases (period > length, period = 1). |
| `web/components/DecisionTimeline.tsx` | modify | Replace inline styles with Tailwind + Axiara tokens. Same columns: Date, Rating, Status, Realized return. Same data shape. |
| `web/app/portfolio/[ticker]/page.tsx` | modify | Read `interval` from `searchParams`. Pass to `api.portfolioTicker(...)`. Render `<TickerChartWorkspace>` instead of `<TickerPriceChart>`. |
| `web/components/TickerPriceChart.tsx` | delete | Replaced by `TickerChartWorkspace`. No other consumers per grep. |
| `web/package.json` | modify | Add `lightweight-charts` (~40KB gzipped) + `vitest` + `@vitest/coverage-v8` as dev deps. |
| `web/vitest.config.ts` | create | Vitest config: jsdom environment for component tests, no React-specific setup needed for the pure-function indicator tests. |
| `web/tests/e2e/ticker-chart.spec.ts` | create | Playwright: page renders the chart container, timeframe toggle changes the URL `?interval=1h` and triggers a re-fetch, decision markers appear (verified via canvas snapshot or a `data-testid` on the marker container if lightweight-charts exposes one — fallback: assert the API was called with the new interval). |

`web/components/PnLChart.tsx` is unchanged — different component on a different page.

## 6. Decisions resolved during spec-writing

These were §8 open questions in the brainstorm; baking in answers here:

1. **Vitest as a new dev dep — YES.** The indicator math (SMA/EMA/RSI) is pure-function logic ideal for unit tests. Adding vitest costs ~one config file + 3 lines in package.json. It's a small surface that opens the door for future logic-heavy components (e.g., portfolio P&L calculations) without the overhead of routing through Playwright. The alternative (Playwright snapshot of rendered chart) is wasteful for testing math.

2. **OHLCVBar REPLACES PricePoint — schema rename, not parallel.** Grep confirms `PricePoint` is only consumed by the `/portfolio/ticker/{ticker}` endpoint today. A parallel schema doubles the surface area without benefit. The OpenAPI regeneration will update `web/lib/types.ts` accordingly.

3. **Interval via `searchParams`, not client state.** `/portfolio/AAPL?interval=1h` is bookmarkable, reload-stable, shareable. Client-state-only would lose the interval on refresh. The Default is `1d` (omitted = `1d` for clean URLs).

## 7. Server-side widening (concrete)

Current schema:
```python
class PricePoint(BaseModel):
    trade_date: str
    close: float
```

New schema:
```python
class OHLCVBar(BaseModel):
    trade_date: str    # ISO date (1d) or ISO datetime UTC (1h)
    open: float
    high: float
    low: float
    close: float
    volume: int
```

`TickerDetailOut.prices: list[OHLCVBar]` replaces `list[PricePoint]`.

`price_cache.fetch_prices(...)` widens:

```python
async def fetch_prices(
    *,
    dashboard_dir: Path,
    user_id: uuid.UUID,
    ticker: str,
    start: str,
    end: str,
    interval: Literal["1d", "1h"] = "1d",
) -> tuple[list[dict[str, Any]], bool]:
    """Returns (bars, data_range_clipped). Hourly is clipped to last 60 days."""
    # Cache key now includes interval so daily + hourly are separately cached.
    # yfinance Ticker.history(start, end, interval=interval) returns OHLCV.
    ...
```

For interval=`"1h"`, if `end - start > 60 days`, clip `start = end - 60 days` and set `data_range_clipped = True`. Endpoint includes the flag in the response so the client renders an inline notice.

## 8. `TickerChartWorkspace` shape

The component wraps lightweight-charts via React refs. Two stacked chart instances:

- **Main chart**: candlestick price series + SMA/EMA overlay line series + volume histogram (with `priceScaleId: "vol"` and `scaleMargins.top: 0.7` so volume sits in the bottom 30% of the same chart).
- **RSI chart**: a second `IChartApi` instance below, sharing a synchronized time scale via `subscribeVisibleTimeRangeChange` (the canonical lightweight-charts pattern for multi-pane).

```tsx
"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createChart, CrosshairMode, ColorType,
  type IChartApi, type ISeriesApi,
} from "lightweight-charts";
import { sma, ema, rsi } from "./TickerChartWorkspace.indicators";
import type { OHLCVBar, DecisionPin } from "@/lib/types";

interface Props {
  bars: OHLCVBar[];
  decisions: DecisionPin[];
  ticker: string;
  interval: "1d" | "1h";
  dataRangeClipped?: boolean;
}

const RATING_COLOR: Record<string, string> = {
  Buy: "#16a34a", Overweight: "#22c55e",
  Hold: "#9ca3af",
  Underweight: "#f97316", Sell: "#dc2626",
};

export default function TickerChartWorkspace(props: Props) {
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!mainContainerRef.current || !rsiContainerRef.current) return;

    const mainChart = createChart(mainContainerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgb(var(--fg-muted))",
        fontFamily: "var(--font-mono, monospace)",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: props.interval === "1h",
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
    });

    const candles = mainChart.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626",
      borderUpColor: "#16a34a", borderDownColor: "#dc2626",
      wickUpColor: "#16a34a", wickDownColor: "#dc2626",
    });
    candles.setData(props.bars.map(b => ({
      time: b.trade_date as any,
      open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    candles.setMarkers(props.decisions.map(d => ({
      time: d.trade_date as any,
      position: ["Buy", "Overweight"].includes(d.rating) ? "belowBar" : "aboveBar",
      color: RATING_COLOR[d.rating] ?? "#9ca3af",
      shape: ["Buy", "Overweight"].includes(d.rating) ? "arrowUp"
           : ["Sell", "Underweight"].includes(d.rating) ? "arrowDown"
           : "circle",
      text: d.raw_return != null ? `${d.rating} ${fmtPct(d.raw_return)}` : d.rating,
    })));

    // Moving average overlays on the price pane
    const overlays = [
      { fn: sma, period: 20, color: "#3A7BD5", title: "SMA(20)" },
      { fn: sma, period: 50, color: "#7C3AED", title: "SMA(50)" },
      { fn: ema, period: 9,  color: "#E8342A", title: "EMA(9)" },
      { fn: ema, period: 21, color: "#F59E0B", title: "EMA(21)" },
    ];
    for (const { fn, period, color, title } of overlays) {
      const line = mainChart.addLineSeries({ color, lineWidth: 1, title });
      line.setData(fn(props.bars, period));
    }

    // Volume histogram in the same chart, bottom 30%
    const volumeSeries = mainChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: "rgba(255,255,255,0.3)",
    });
    mainChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.7, bottom: 0 } });
    volumeSeries.setData(props.bars.map(b => ({
      time: b.trade_date as any,
      value: b.volume,
      color: b.close >= b.open ? "rgba(22,163,74,0.5)" : "rgba(220,38,38,0.5)",
    })));

    // RSI chart in the second container, synchronized time scale
    const rsiChart = createChart(rsiContainerRef.current, { /* similar config */ });
    const rsiSeries = rsiChart.addLineSeries({ color: "#3A7BD5", lineWidth: 1 });
    rsiSeries.setData(rsi(props.bars, 14));
    rsiSeries.createPriceLine({ price: 70, color: "rgba(220,38,38,0.4)", lineStyle: 2, axisLabelVisible: false });
    rsiSeries.createPriceLine({ price: 30, color: "rgba(22,163,74,0.4)", lineStyle: 2, axisLabelVisible: false });

    // Sync time scale
    const sync = mainChart.timeScale().subscribeVisibleTimeRangeChange(r => {
      if (r) rsiChart.timeScale().setVisibleRange(r);
    });

    mainChart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();

    return () => {
      mainChart.timeScale().unsubscribeVisibleTimeRangeChange(sync);
      mainChart.remove();
      rsiChart.remove();
    };
  }, [props.bars, props.decisions, props.interval]);

  function setInterval(next: "1d" | "1h") {
    const url = new URL(window.location.href);
    if (next === "1d") url.searchParams.delete("interval");
    else url.searchParams.set("interval", next);
    router.replace(url.pathname + url.search);
  }

  return (
    <div className="rounded-xl border border-border/60 bg-surface/40 backdrop-blur-sm overflow-hidden">
      <header className="flex items-center justify-between border-b border-border/40 px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h2 className="font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">{props.ticker}</h2>
          <span className="text-[11px] text-fg-subtle">
            candles · sma(20,50) · ema(9,21) · volume · rsi(14)
          </span>
        </div>
        <div role="tablist" className="inline-flex items-center rounded-md border border-border/60 bg-surface/40">
          <button onClick={() => setInterval("1d")} className={cn("px-2.5 py-1 text-xs", props.interval === "1d" ? "text-fg bg-elevated" : "text-fg-muted")}>1D</button>
          <button onClick={() => setInterval("1h")} className={cn("px-2.5 py-1 text-xs", props.interval === "1h" ? "text-fg bg-elevated" : "text-fg-muted")}>1H</button>
        </div>
      </header>
      {props.dataRangeClipped && (
        <p className="border-b border-amber-500/20 bg-amber-500/5 px-4 py-2 text-xs text-amber-200/80">
          Hourly data limited to the last 60 days by the upstream provider.
        </p>
      )}
      <div ref={mainContainerRef} className="h-[420px]" />
      <div ref={rsiContainerRef} className="h-[120px] border-t border-border/40" />
    </div>
  );
}
```

The two-chart-instance pattern (price+volume in one, RSI in another) is the canonical multi-pane approach for lightweight-charts — the library doesn't expose first-class "panes" yet, but `subscribeVisibleTimeRangeChange` makes the two charts behave as one.

## 9. Indicator math (`TickerChartWorkspace.indicators.ts`)

All three are pure-function transformations over the bar array. Returns time + value pairs in lightweight-charts's expected shape.

```typescript
import type { OHLCVBar } from "@/lib/types";

export interface IndicatorPoint { time: string; value: number; }

export function sma(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  if (period < 1) throw new Error("SMA period must be >= 1");
  const out: IndicatorPoint[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) out.push({ time: bars[i].trade_date, value: sum / period });
  }
  return out;
}

export function ema(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  if (period < 1) throw new Error("EMA period must be >= 1");
  if (bars.length === 0) return [];
  const k = 2 / (period + 1);
  const out: IndicatorPoint[] = [];
  let prev = bars[0].close;
  out.push({ time: bars[0].trade_date, value: prev });
  for (let i = 1; i < bars.length; i++) {
    prev = bars[i].close * k + prev * (1 - k);
    out.push({ time: bars[i].trade_date, value: prev });
  }
  return out;
}

export function rsi(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  // Wilder's smoothing. Returns RSI in [0, 100]. Empty for the first `period` bars.
  if (period < 1) throw new Error("RSI period must be >= 1");
  if (bars.length < period + 1) return [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = bars[i].close - bars[i - 1].close;
    if (d > 0) avgGain += d; else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  const out: IndicatorPoint[] = [];
  out.push({ time: bars[period].trade_date, value: 100 - 100 / (1 + avgGain / (avgLoss || 1e-10)) });
  for (let i = period + 1; i < bars.length; i++) {
    const d = bars[i].close - bars[i - 1].close;
    const gain = d > 0 ? d : 0;
    const loss = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgGain / (avgLoss || 1e-10);
    out.push({ time: bars[i].trade_date, value: 100 - 100 / (1 + rs) });
  }
  return out;
}
```

Vitest test cases:
- `sma`: monotone input (1..N) yields midpoint of trailing window; all-same prices yield flat line; period > length yields empty.
- `ema`: emit one value per bar (no skip); first value equals first close; weights match `k = 2/(period+1)`.
- `rsi`: all-gain input → 100; all-loss → 0; alternating equal gain/loss → 50; period > length-1 → empty.

## 10. Acceptance criteria

The implementation is done when all of these are true:

- [ ] `/portfolio/[ticker]` renders the new `TickerChartWorkspace` with 3 visual panes: candlesticks + moving-average overlays + decision markers (top), volume histogram (middle), RSI(14) with 30/70 reference lines (bottom).
- [ ] `?interval=1h` switches to hourly bars; `1D`/`1H` toggle buttons in the header swap the URL.
- [ ] Hourly with date range > 60 days shows the inline "limited to last 60 days" notice.
- [ ] SMA(20), SMA(50), EMA(9), EMA(21) overlay with distinct colors; legend in the header tells you what's plotted.
- [ ] Volume bars are colored green for up-days (close ≥ open) and red for down-days.
- [ ] Decision markers: ↑ arrow (green) for Buy/Overweight, ↓ arrow (red) for Sell/Underweight, ● circle (grey) for Hold; text shows rating + realized return %.
- [ ] DecisionTimeline below uses Tailwind + Axiara tokens — no inline styles.
- [ ] Indicator math has vitest unit tests covering monotone, all-same, edge cases.
- [ ] Playwright e2e: chart container present, timeframe toggle updates URL, decisions visible.
- [ ] No regression for tickers with no price data (graceful empty state).
- [ ] No regression for tickers with no decisions (chart renders without markers; table shows "No decisions yet").
- [ ] `web/components/TickerPriceChart.tsx` deleted; no broken imports anywhere.

# Technical Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Recharts line chart on `/portfolio/[ticker]` with a 3-pane TradingView lightweight-charts workspace (candlestick + SMA/EMA overlays + decision markers / volume histogram / RSI(14)) plus a Daily/Hourly timeframe toggle and an Axiara-restyled DecisionTimeline.

**Architecture:** Server widens `PricePoint` → `OHLCVBar` (O/H/L/C/V) and `fetch_prices` accepts `interval: Literal["1d", "1h"]`. Web installs `lightweight-charts` + `vitest`, regenerates OpenAPI types, ships a new `TickerChartWorkspace` client component (two stacked chart instances with time-scale sync), pure-function indicator math with unit tests, restyled DecisionTimeline, and wires it all together via `searchParams.interval` on the page.

**Tech Stack:** TradingView lightweight-charts (~40KB gzip, MIT-licensed), Next.js 15 server/client component split, FastAPI + SQLAlchemy + yfinance, Vitest for unit tests, Playwright for e2e.

**Spec:** [`docs/superpowers/plans/2026-05-21-technical-chart-design.md`](./2026-05-21-technical-chart-design.md)

---

## Before You Start

This plan assumes you can answer "yes" to all of these:

- You can run `npm run codegen` in `web/` (requires `uv` installed at the parent path — see `web/package.json`).
- You can run `cd server && uv run pytest -q` and have all baseline tests pass.
- You have `docker compose` (only used for an optional dev-server smoke).
- The live prod VM stays running — Phase 6 will run the workflow against this branch and against main, but doesn't require manual VM interaction.

Confirmed open questions from spec §6 + §8 (final answers baked in):

- **Vitest IS being added** as a dev dependency. The indicator math lives in pure functions ideal for vitest unit tests.
- **`OHLCVBar` REPLACES `PricePoint`** in `server/app/schemas/portfolio.py`. Only consumer is `/portfolio/ticker/{ticker}`. Rename is cleaner than parallel schemas.
- **Interval lives in `searchParams`**: `/portfolio/AAPL?interval=1h`. Default (no param) means `1d`.
- **Hourly time encoding**: server returns `trade_date` as ISO date string (`"2026-05-21"`) for daily bars and ISO datetime UTC string (`"2026-05-21T14:00:00Z"`) for hourly bars. Client converts the latter to unix seconds for lightweight-charts via `Math.floor(new Date(s).getTime() / 1000)`.
- **`fetch_prices` return signature** changes from `list[dict]` to a `(bars, data_range_clipped)` tuple so the endpoint can surface the "hourly limited to 60 days" notice.

---

## Phase 1 — Setup

### Task 1: Create the feature branch

**Files:** none (git only).

- [ ] **Step 1: Sync local main**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git fetch fork
git checkout main
git pull fork main
```

Expected: `Already up to date.` or fast-forward to current `fork/main` HEAD (which includes commit `accb24f` — the technical-chart design doc).

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b feature/technical-chart
```

Expected: `Switched to a new branch 'feature/technical-chart'`.

---

## Phase 2 — Server: schema + cache + endpoint widening

### Task 2: Write failing tests for the new server shape

**Files:**
- Create: `server/tests/test_price_cache_interval.py`
- Create: `server/tests/test_portfolio_ticker_interval.py`

- [ ] **Step 1: Write failing tests for `fetch_prices(interval=...)`**

Create `server/tests/test_price_cache_interval.py`:

```python
# server/tests/test_price_cache_interval.py
"""Unit tests for price_cache.fetch_prices interval handling.

These tests do NOT hit yfinance — they mock the network layer and verify
our wrapper's behavior: cache key derivation, interval validation,
hourly window clipping, OHLCV shape preservation.
"""
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from app.services import price_cache


def _make_yf_daily_df():
    return pd.DataFrame(
        {
            "Open":   [100.0, 101.0, 102.0],
            "High":   [101.0, 102.0, 103.0],
            "Low":    [ 99.0, 100.0, 101.0],
            "Close":  [100.5, 101.5, 102.5],
            "Volume": [10000, 11000, 12000],
        },
        index=pd.DatetimeIndex(
            ["2026-05-19", "2026-05-20", "2026-05-21"],
            name="Date", tz="UTC",
        ),
    )


def _make_yf_hourly_df():
    return pd.DataFrame(
        {
            "Open":   [100.0, 100.5, 101.0],
            "High":   [100.7, 101.2, 101.5],
            "Low":    [ 99.8, 100.3, 100.8],
            "Close":  [100.5, 101.0, 101.3],
            "Volume": [ 1000,  1100,  1200],
        },
        index=pd.DatetimeIndex(
            ["2026-05-21 13:00:00", "2026-05-21 14:00:00", "2026-05-21 15:00:00"],
            name="Datetime", tz="UTC",
        ),
    )


@pytest.mark.asyncio
async def test_daily_returns_ohlcv_bars(tmp_path):
    """interval='1d' returns OHLCV bars keyed by trade_date as ISO date."""
    with patch.object(price_cache, "_fetch_yf", AsyncMock(return_value=_make_yf_daily_df())):
        bars, clipped = await price_cache.fetch_prices(
            dashboard_dir=tmp_path, user_id=uuid.uuid4(),
            ticker="AAPL", start="2026-05-19", end="2026-05-21",
            interval="1d",
        )
    assert clipped is False
    assert len(bars) == 3
    assert bars[0] == {
        "trade_date": "2026-05-19",
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": 10000,
    }


@pytest.mark.asyncio
async def test_hourly_returns_iso_datetime_utc(tmp_path):
    """interval='1h' returns OHLCV bars keyed by trade_date as ISO datetime UTC."""
    with patch.object(price_cache, "_fetch_yf", AsyncMock(return_value=_make_yf_hourly_df())):
        bars, clipped = await price_cache.fetch_prices(
            dashboard_dir=tmp_path, user_id=uuid.uuid4(),
            ticker="AAPL", start="2026-05-21", end="2026-05-22",
            interval="1h",
        )
    assert clipped is False
    assert len(bars) == 3
    # ISO datetime with explicit UTC timezone (Z suffix).
    assert bars[0]["trade_date"] == "2026-05-21T13:00:00Z"
    assert bars[0]["open"] == 100.0
    assert bars[0]["volume"] == 1000


@pytest.mark.asyncio
async def test_hourly_clips_to_60_days(tmp_path):
    """Hourly request with >60-day range gets clipped + clipped=True."""
    with patch.object(price_cache, "_fetch_yf", AsyncMock(return_value=_make_yf_hourly_df())) as m:
        bars, clipped = await price_cache.fetch_prices(
            dashboard_dir=tmp_path, user_id=uuid.uuid4(),
            ticker="AAPL", start="2026-01-01", end="2026-05-21",
            interval="1h",
        )
    assert clipped is True
    # Underlying yfinance call was invoked with a clipped start (60 days before end).
    call_kwargs = m.call_args.kwargs
    from datetime import datetime
    actual_start = datetime.strptime(call_kwargs["start"], "%Y-%m-%d")
    expected_start = datetime.strptime("2026-03-22", "%Y-%m-%d")  # 60 days before 2026-05-21
    assert actual_start == expected_start, f"expected clip start {expected_start}, got {actual_start}"


@pytest.mark.asyncio
async def test_cache_key_includes_interval(tmp_path):
    """Daily and hourly for the same ticker+range hit different cache files."""
    user_id = uuid.uuid4()
    common = dict(dashboard_dir=tmp_path, user_id=user_id, ticker="AAPL",
                  start="2026-05-19", end="2026-05-21")

    with patch.object(price_cache, "_fetch_yf", AsyncMock(return_value=_make_yf_daily_df())):
        await price_cache.fetch_prices(**common, interval="1d")
    with patch.object(price_cache, "_fetch_yf", AsyncMock(return_value=_make_yf_hourly_df())):
        await price_cache.fetch_prices(**common, interval="1h")

    user_dir = tmp_path / str(user_id) / "price-cache"
    files = sorted(p.name for p in user_dir.glob("*.json"))
    # Both cache files exist; filenames differ in the interval suffix.
    assert len(files) == 2
    assert any("1d" in f for f in files)
    assert any("1h" in f for f in files)
```

- [ ] **Step 2: Write failing tests for the endpoint**

Create `server/tests/test_portfolio_ticker_interval.py`:

```python
# server/tests/test_portfolio_ticker_interval.py
"""End-to-end test of /portfolio/ticker/{ticker}?interval=... shape.

The yfinance layer is mocked so the test is deterministic."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services import price_cache


@pytest.mark.asyncio
async def test_endpoint_default_interval_is_1d(async_client_authed):
    """No ?interval query param -> daily bars, OHLCV in response."""
    with patch.object(price_cache, "fetch_prices",
                      AsyncMock(return_value=([{
                          "trade_date": "2026-05-21",
                          "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                          "volume": 10000,
                      }], False))):
        res = await async_client_authed.get("/portfolio/ticker/AAPL")
    assert res.status_code == 200
    body = res.json()
    assert body["prices"][0]["open"] == 100.0
    assert "data_range_clipped" in body
    assert body["data_range_clipped"] is False


@pytest.mark.asyncio
async def test_endpoint_hourly_returns_clipped_flag(async_client_authed):
    """?interval=1h passes through; clipped flag in response if backend clipped."""
    with patch.object(price_cache, "fetch_prices",
                      AsyncMock(return_value=([{
                          "trade_date": "2026-05-21T14:00:00Z",
                          "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2,
                          "volume": 1000,
                      }], True))):
        res = await async_client_authed.get("/portfolio/ticker/AAPL?interval=1h")
    assert res.status_code == 200
    body = res.json()
    assert body["prices"][0]["trade_date"] == "2026-05-21T14:00:00Z"
    assert body["data_range_clipped"] is True


@pytest.mark.asyncio
async def test_endpoint_rejects_invalid_interval(async_client_authed):
    """?interval=invalid -> 422."""
    res = await async_client_authed.get("/portfolio/ticker/AAPL?interval=5m")
    assert res.status_code == 422
```

> **Note on test fixtures**: This plan assumes `async_client_authed` exists in the test suite. If it doesn't (the realtime-opt-in plan also discovered this), the implementer must replicate the inline `client` + `make_jwt()` + `authed_user` pattern from `server/tests/test_runs_active_count.py`. The TEST BODIES stay the same; only the fixture-name parameters change.

- [ ] **Step 3: Run to verify all 7 tests fail**

```bash
cd server && uv run pytest tests/test_price_cache_interval.py tests/test_portfolio_ticker_interval.py -v 2>&1 | tail -20
```

Expected: 7 failures, most likely with `TypeError: fetch_prices() got an unexpected keyword argument 'interval'` or `AttributeError: module 'app.services.price_cache' has no attribute '_fetch_yf'`. These are the tests we need to make pass in Task 3.

No commit (combined with Task 3).

---

### Task 3: Implement OHLCVBar schema + interval-aware fetch_prices + endpoint

**Files:**
- Modify: `server/app/schemas/portfolio.py`
- Modify: `server/app/services/price_cache.py`
- Modify: `server/app/routers/portfolio.py`

- [ ] **Step 1: Rename PricePoint → OHLCVBar in the schema**

Open `server/app/schemas/portfolio.py`. Replace the `PricePoint` class with `OHLCVBar`:

```python
class OHLCVBar(BaseModel):
    """One bar of OHLCV market data.

    `trade_date` is ISO date "YYYY-MM-DD" for daily (interval=1d)
    or ISO datetime UTC "YYYY-MM-DDTHH:MM:SSZ" for hourly (interval=1h).
    The client decodes accordingly.
    """
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
```

Find every reference to `PricePoint` in this file and rename to `OHLCVBar`. The `TickerDetailOut` reference becomes:

```python
class TickerDetailOut(BaseModel):
    ticker: str
    prices: list[OHLCVBar]
    decisions: list[DecisionPin]
    data_range_clipped: bool = False  # NEW: True when hourly request was clipped to 60 days
```

- [ ] **Step 2: Widen `fetch_prices` to accept `interval`**

Open `server/app/services/price_cache.py`. The current signature is:

```python
async def fetch_prices(
    dashboard_dir: Path,
    *,
    user_id: uuid.UUID,
    ticker: str,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
```

Replace with:

```python
from typing import Literal
from datetime import datetime, timedelta

Interval = Literal["1d", "1h"]

# Module-level shim around the yfinance call so tests can patch it.
# Keep the import + actual yfinance call internal to this function;
# callers patch `_fetch_yf` rather than monkeypatching yfinance.
async def _fetch_yf(ticker: str, *, start: str, end: str, interval: str):
    """Returns a pandas DataFrame with columns: Open, High, Low, Close, Volume.
    Index is DatetimeIndex (tz-aware UTC for hourly, naive date for daily)."""
    import yfinance as yf
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: yf.Ticker(ticker).history(start=start, end=end, interval=interval, auto_adjust=False),
    )


async def fetch_prices(
    dashboard_dir: Path,
    *,
    user_id: uuid.UUID,
    ticker: str,
    start: str,
    end: str,
    interval: Interval = "1d",
) -> tuple[list[dict[str, Any]], bool]:
    """Return (bars, data_range_clipped) for `ticker` from `start` to `end`.

    For interval='1h', the start is clipped to max 60 days before `end`
    (yfinance free-tier hourly limit) and the second tuple element is
    True if any clipping happened.

    bars are dicts with keys: trade_date (str), open, high, low, close (float),
    volume (int). trade_date is ISO date for daily, ISO datetime UTC for hourly.
    """
    check_segment("ticker", ticker, TICKER_RE)
    check_segment("start", start, DATE_RE)
    check_segment("end", end, DATE_RE)

    # Hourly window clipping.
    clipped = False
    effective_start = start
    if interval == "1h":
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        sixty_days_before_end = end_dt - timedelta(days=60)
        if start_dt < sixty_days_before_end:
            effective_start = sixty_days_before_end.strftime("%Y-%m-%d")
            clipped = True

    # Cache key now includes interval so daily + hourly cache separately.
    cache_dir = dashboard_dir / str(user_id) / "price-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{ticker}-{effective_start}-{end}-{interval}.json"

    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < _ttl_seconds():
        with cache_file.open() as f:
            return json.load(f), clipped

    df = await _fetch_yf(ticker, start=effective_start, end=end, interval=interval)
    if df is None or df.empty:
        raise PriceFetchError(f"yfinance returned empty data for {ticker}")

    bars: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        if interval == "1d":
            trade_date = ts.strftime("%Y-%m-%d")
        else:
            # Hourly: emit ISO datetime UTC with Z suffix.
            # yfinance hourly index is tz-aware; convert to UTC then format.
            if ts.tz is None:
                ts_utc = ts.tz_localize("UTC")
            else:
                ts_utc = ts.tz_convert("UTC")
            trade_date = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        bars.append({
            "trade_date": trade_date,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })

    with cache_file.open("w") as f:
        json.dump(bars, f)
    return bars, clipped
```

- [ ] **Step 3: Update the endpoint to accept `?interval=`**

Open `server/app/routers/portfolio.py`. The current `get_ticker_detail` signature:

```python
async def get_ticker_detail(
    ticker: str = PathParam(..., pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TickerDetailOut:
```

Add an `interval` query parameter:

```python
from typing import Literal
from fastapi import Query

async def get_ticker_detail(
    ticker: str = PathParam(..., pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$"),
    interval: Literal["1d", "1h"] = Query("1d"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TickerDetailOut:
```

Find the call to `_fetch_prices(...)` (around line 170 per earlier grep) and pass `interval=interval` plus capture the tuple return:

```python
try:
    price_points, data_range_clipped = await _fetch_prices(
        # ... existing args ...
        interval=interval,
    )
except PriceFetchError:
    # Existing fallback: return 200 with empty prices.
    return TickerDetailOut(
        ticker=ticker, prices=[], decisions=decisions, data_range_clipped=False,
    )

return TickerDetailOut(
    ticker=ticker,
    prices=[OHLCVBar(**p) for p in price_points],
    decisions=decisions,
    data_range_clipped=data_range_clipped,
)
```

Replace any `PricePoint` imports/refs with `OHLCVBar`.

- [ ] **Step 4: Run the new tests + full suite**

```bash
cd server
uv run pytest tests/test_price_cache_interval.py tests/test_portfolio_ticker_interval.py -v
uv run pytest -q
```

Expected:
- 7 new tests pass.
- Full server suite: previous-baseline + 7. No regressions.

If `async_client_authed` doesn't exist, see the note in Task 2 step 2 — replicate the inline pattern.

- [ ] **Step 5: Commit**

```bash
git add server/app/schemas/portfolio.py \
        server/app/services/price_cache.py \
        server/app/routers/portfolio.py \
        server/tests/test_price_cache_interval.py \
        server/tests/test_portfolio_ticker_interval.py
git commit -m "feat(server): widen PricePoint -> OHLCVBar + interval support

- Rename PricePoint schema to OHLCVBar with open/high/low/close/volume.
- fetch_prices() accepts interval='1d'|'1h'; cache key includes interval
  so daily and hourly are separately cached. Hourly is clipped to last
  60 days (yfinance free-tier limit), returns (bars, clipped) tuple.
- /portfolio/ticker/{ticker} accepts ?interval=1d|1h query param.
  Response includes data_range_clipped bool.
- Hourly bar trade_date is ISO datetime UTC (Z suffix); daily stays as
  ISO date. Client decodes both forms.
- 7 new pytest tests cover OHLCV shape, hourly clipping, separate cache
  keys, interval validation, and endpoint response shape."
```

---

## Phase 3 — Web infrastructure

### Task 4: Install lightweight-charts

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`

- [ ] **Step 1: Install the dependency**

```bash
cd web && npm install lightweight-charts
```

Expected: `+ lightweight-charts@5.x.x` (or whatever's current) added to dependencies.

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd web && node -e "const m = require('lightweight-charts'); console.log(typeof m.createChart);"
```

Expected: `function`.

- [ ] **Step 3: Commit**

```bash
git add web/package.json web/package-lock.json
git commit -m "chore(web): add lightweight-charts dependency

~40KB gzipped, MIT-licensed, native candlestick + line + histogram
series with built-in crosshair and time-scale synchronization. Used
by TickerChartWorkspace in the next commits."
```

---

### Task 5: Add vitest as a dev dep + config

**Files:**
- Modify: `web/package.json`
- Create: `web/vitest.config.ts`

- [ ] **Step 1: Install vitest + jsdom**

```bash
cd web && npm install --save-dev vitest @vitest/coverage-v8
```

Expected: `+ vitest@1.x.x` added to devDependencies. (jsdom is optional — pure-function tests don't need a DOM. Skip jsdom for now.)

- [ ] **Step 2: Add the `test` script to `web/package.json`**

In the `"scripts"` block of `web/package.json`, add:

```json
"test": "vitest run",
"test:watch": "vitest",
```

- [ ] **Step 3: Create `web/vitest.config.ts`**

```typescript
// web/vitest.config.ts
import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  test: {
    // No globals — explicit imports keep IDE jump-to-definition working.
    environment: "node",
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: [
      "node_modules/**",
      ".next/**",
      "tests/e2e/**",  // Playwright lives here, not vitest.
    ],
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "."),
    },
  },
});
```

- [ ] **Step 4: Smoke-test vitest runs**

Create a throwaway test to confirm config works:

```bash
cat > web/lib/__smoke.test.ts <<'EOF'
import { expect, test } from "vitest";
test("vitest works", () => { expect(2 + 2).toBe(4); });
EOF
cd web && npm test 2>&1 | tail -8
rm web/lib/__smoke.test.ts
```

Expected: `1 passed`. Vitest runs, picks up the test, exits cleanly.

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts
git commit -m "chore(web): add vitest for unit tests

Vitest set up with node environment (no DOM — indicator math is pure
function logic). Excludes tests/e2e (Playwright's territory). Aliases
@/ to web/ root matching tsconfig.

Scripts: npm test (one-shot) + npm run test:watch (dev loop)."
```

---

### Task 6: Regenerate OpenAPI types after server schema change

**Files:**
- Modify: `web/lib/openapi-types.ts` (generated)
- Modify: `server/openapi.json` (generated artifact)

- [ ] **Step 1: Run the codegen**

```bash
cd web && npm run codegen
```

Expected: regenerates `web/lib/openapi-types.ts` from the live server's openapi.json. New OHLCVBar schema appears; old PricePoint disappears.

- [ ] **Step 2: Verify the new types are present**

```bash
grep -E "OHLCVBar|PricePoint" web/lib/openapi-types.ts | head -10
```

Expected:
- `OHLCVBar` appears as a TypeScript type definition.
- `PricePoint` is GONE from the file (we renamed it, didn't add parallel).

- [ ] **Step 3: Update `web/lib/types.ts` to export the new name**

Open `web/lib/types.ts`. Find:

```typescript
export type PricePoint = components["schemas"]["PricePoint"];
```

Replace with:

```typescript
export type OHLCVBar = components["schemas"]["OHLCVBar"];
```

(Keep all other exports unchanged. `DecisionPin`, `TickerDetailOut` stay.)

- [ ] **Step 4: Verify TS builds**

```bash
cd web && npm run build 2>&1 | tail -10
```

Expected: TypeScript errors in files that reference `PricePoint` — `TickerPriceChart.tsx` (which we're deleting anyway) and `portfolio/[ticker]/page.tsx`. We'll fix these in later tasks. Build will fail; that's OK for now.

> **Alternative**: skip Step 4. The next task will delete `TickerPriceChart.tsx` and update `page.tsx`, after which the build will be clean.

- [ ] **Step 5: Commit**

```bash
git add web/lib/openapi-types.ts web/lib/types.ts server/openapi.json
git commit -m "chore(web): regenerate OpenAPI types — OHLCVBar replaces PricePoint

Run \`npm run codegen\` after the server schema rename. TypeScript build
intentionally fails at this point (TickerPriceChart.tsx still imports
PricePoint); next commits delete that component and rewire the page."
```

---

## Phase 4 — Web components

### Task 7: Implement indicator math + unit tests

**Files:**
- Create: `web/components/TickerChartWorkspace.indicators.ts`
- Create: `web/components/TickerChartWorkspace.indicators.test.ts`

- [ ] **Step 1: Write failing tests**

Create `web/components/TickerChartWorkspace.indicators.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import type { OHLCVBar } from "@/lib/types";
import { ema, rsi, sma } from "./TickerChartWorkspace.indicators";

function makeBars(closes: number[]): OHLCVBar[] {
  return closes.map((close, i) => ({
    trade_date: `2026-01-${String(i + 1).padStart(2, "0")}`,
    open: close, high: close, low: close, close, volume: 1000,
  }));
}

describe("sma", () => {
  it("returns trailing average of the period", () => {
    const bars = makeBars([1, 2, 3, 4, 5]);
    const out = sma(bars, 3);
    // First 2 bars skipped; from bar index 2 onward: avg(1,2,3)=2, avg(2,3,4)=3, avg(3,4,5)=4
    expect(out).toEqual([
      { time: "2026-01-03", value: 2 },
      { time: "2026-01-04", value: 3 },
      { time: "2026-01-05", value: 4 },
    ]);
  });

  it("flat input gives flat output", () => {
    const bars = makeBars([10, 10, 10, 10, 10]);
    const out = sma(bars, 3);
    expect(out.every((p) => p.value === 10)).toBe(true);
  });

  it("period larger than length yields empty", () => {
    const bars = makeBars([1, 2]);
    expect(sma(bars, 5)).toEqual([]);
  });

  it("period of 1 yields the raw closes", () => {
    const bars = makeBars([1, 2, 3]);
    const out = sma(bars, 1);
    expect(out.map((p) => p.value)).toEqual([1, 2, 3]);
  });
});

describe("ema", () => {
  it("emits one point per bar; first equals first close", () => {
    const bars = makeBars([10, 11, 12]);
    const out = ema(bars, 3);
    expect(out.length).toBe(3);
    expect(out[0].value).toBe(10);
  });

  it("approaches input as period -> infinity (slow smoothing)", () => {
    const bars = makeBars([100, 200, 200, 200, 200, 200, 200, 200]);
    const out = ema(bars, 100);
    // With period=100, k = 2/101 ~= 0.0198. After 7 jumps from 100 to 200,
    // EMA should still be quite close to 100 (i.e., heavily smoothed).
    expect(out[out.length - 1].value).toBeLessThan(120);
  });

  it("period of 1 yields the raw closes (k=1)", () => {
    const bars = makeBars([1, 2, 3]);
    const out = ema(bars, 1);
    expect(out.map((p) => p.value)).toEqual([1, 2, 3]);
  });

  it("empty input yields empty output", () => {
    expect(ema([], 14)).toEqual([]);
  });
});

describe("rsi", () => {
  it("all-gain input yields 100", () => {
    const bars = makeBars([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);
    const out = rsi(bars, 14);
    expect(out[out.length - 1].value).toBeCloseTo(100, 1);
  });

  it("all-loss input yields 0", () => {
    const bars = makeBars([16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]);
    const out = rsi(bars, 14);
    expect(out[out.length - 1].value).toBeCloseTo(0, 1);
  });

  it("alternating equal gain/loss converges to 50", () => {
    // 30 bars alternating +1/-1 around 100 to let RSI converge.
    const closes: number[] = [];
    let v = 100;
    for (let i = 0; i < 30; i++) { v += i % 2 === 0 ? 1 : -1; closes.push(v); }
    const bars = makeBars(closes);
    const out = rsi(bars, 14);
    expect(out[out.length - 1].value).toBeCloseTo(50, 0);
  });

  it("returns empty if bars.length <= period", () => {
    expect(rsi(makeBars([1, 2, 3]), 14)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify all 12 tests fail**

```bash
cd web && npm test 2>&1 | tail -15
```

Expected: all 12 tests fail (file doesn't exist).

- [ ] **Step 3: Implement the indicators**

Create `web/components/TickerChartWorkspace.indicators.ts`:

```typescript
import type { OHLCVBar } from "@/lib/types";

export interface IndicatorPoint {
  time: string;
  value: number;
}

export function sma(bars: OHLCVBar[], period: number): IndicatorPoint[] {
  if (period < 1) throw new Error("SMA period must be >= 1");
  const out: IndicatorPoint[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) {
      out.push({ time: bars[i].trade_date, value: sum / period });
    }
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
  if (period < 1) throw new Error("RSI period must be >= 1");
  if (bars.length <= period) return [];

  // Wilder's smoothing: initial avg from the first `period` deltas,
  // then EMA-like recursion with alpha = 1/period.
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = bars[i].close - bars[i - 1].close;
    if (d > 0) avgGain += d;
    else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;

  const out: IndicatorPoint[] = [];
  const epsilon = 1e-10;
  out.push({
    time: bars[period].trade_date,
    value: 100 - 100 / (1 + avgGain / (avgLoss || epsilon)),
  });

  for (let i = period + 1; i < bars.length; i++) {
    const d = bars[i].close - bars[i - 1].close;
    const gain = d > 0 ? d : 0;
    const loss = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgGain / (avgLoss || epsilon);
    out.push({
      time: bars[i].trade_date,
      value: 100 - 100 / (1 + rs),
    });
  }

  return out;
}
```

- [ ] **Step 4: Run the tests + verify all pass**

```bash
cd web && npm test 2>&1 | tail -10
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/components/TickerChartWorkspace.indicators.ts \
        web/components/TickerChartWorkspace.indicators.test.ts
git commit -m "feat(web): indicator math (SMA/EMA/RSI) for TickerChartWorkspace

Pure functions over OHLCVBar arrays. SMA uses trailing window sum;
EMA uses k=2/(period+1) recursion; RSI uses Wilder's smoothing
(alpha=1/period). 12 vitest cases cover happy path, edge cases
(period=1, period > length, empty input), and boundary behavior
(all-gain -> 100, all-loss -> 0, alternating -> 50)."
```

---

### Task 8: Implement TickerChartWorkspace component

**Files:**
- Create: `web/components/TickerChartWorkspace.tsx`

- [ ] **Step 1: Write the component**

```tsx
// web/components/TickerChartWorkspace.tsx
"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
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

    const candles = mainChart.addCandlestickSeries({
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

    candles.setMarkers(
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
      const line = mainChart.addLineSeries({ color, lineWidth: 1, title });
      line.setData(fn(bars, period).map((p) => ({ time: toLwcTime(p.time), value: p.value })));
    }

    // Volume histogram in the same chart, bottom 30%.
    const volumeSeries = mainChart.addHistogramSeries({
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
    const rsiSeries = rsiChart.addLineSeries({
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
    const mainToRsi = mainChart
      .timeScale()
      .subscribeVisibleLogicalRangeChange((range) => {
        if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
      });
    const rsiToMain = rsiChart
      .timeScale()
      .subscribeVisibleLogicalRangeChange((range) => {
        if (range) mainChart.timeScale().setVisibleLogicalRange(range);
      });

    mainChart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();

    return () => {
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(mainToRsi);
      rsiChart.timeScale().unsubscribeVisibleLogicalRangeChange(rsiToMain);
      mainChart.remove();
      rsiChart.remove();
    };
  }, [bars, decisions, interval]);

  function setInterval(next: "1d" | "1h") {
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
          className="inline-flex items-center rounded-md border border-border/60 bg-surface/40"
        >
          <button
            type="button"
            role="tab"
            aria-selected={interval === "1d"}
            onClick={() => setInterval("1d")}
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
            onClick={() => setInterval("1h")}
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
```

- [ ] **Step 2: Verify TypeScript builds**

```bash
cd web && npm run build 2>&1 | tail -10
```

Expected: TickerChartWorkspace compiles. Build may still fail on `page.tsx` (still references old TickerPriceChart). That's fixed in Task 10.

- [ ] **Step 3: Commit**

```bash
git add web/components/TickerChartWorkspace.tsx
git commit -m "feat(web): TickerChartWorkspace component (lightweight-charts)

Two stacked IChartApi instances — candlesticks+overlays+volume on top,
RSI(14) below — synchronized via subscribeVisibleLogicalRangeChange.

Daily/Hourly toggle uses Next.js router.replace to update ?interval
in searchParams (server re-renders the page with new bars).

Decision pins become arrow markers: up-arrow for Buy/Overweight,
down-arrow for Sell/Underweight, circle for Hold; text = rating +
realized-return %.

Time encoding: ISO date string for daily (lightweight-charts native),
unix seconds for hourly (computed from the Z-suffixed ISO datetime)."
```

---

### Task 9: Restyle DecisionTimeline to Axiara tokens

**Files:**
- Modify: `web/components/DecisionTimeline.tsx`

- [ ] **Step 1: Rewrite the component with Tailwind + Axiara tokens**

Replace the entire contents of `web/components/DecisionTimeline.tsx`:

```tsx
// web/components/DecisionTimeline.tsx
import type { DecisionPin } from "@/lib/types";
import { cn } from "@/lib/cn";

function pct(x: number | null): string {
  if (x === null || x === undefined) return "—";
  const sign = x >= 0 ? "+" : "";
  return `${sign}${(x * 100).toFixed(2)}%`;
}

function pctColor(x: number | null): string {
  if (x === null || x === undefined) return "text-fg-subtle";
  return x >= 0 ? "text-success" : "text-danger";
}

export default function DecisionTimeline({
  decisions,
}: {
  decisions: DecisionPin[];
}) {
  if (decisions.length === 0) {
    return (
      <p className="px-4 py-6 text-sm text-fg-muted">
        No decisions yet for this ticker.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-surface/40 backdrop-blur-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/40 text-left">
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              Date
            </th>
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              Rating
            </th>
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
              Status
            </th>
            <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle text-right">
              Realized return
            </th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d, i) => (
            <tr
              key={`${d.trade_date}-${d.rating}-${i}`}
              className="border-b border-border/30 transition-colors last:border-0 hover:bg-surface/60"
            >
              <td className="px-4 py-2.5 font-mono text-fg-muted">{d.trade_date}</td>
              <td className="px-4 py-2.5 text-fg">{d.rating}</td>
              <td
                className={cn(
                  "px-4 py-2.5 font-mono text-xs",
                  d.status === "pending" ? "text-fg-subtle" : "text-fg-muted",
                )}
              >
                {d.status}
              </td>
              <td
                className={cn(
                  "px-4 py-2.5 text-right font-mono tabular-nums",
                  pctColor(d.raw_return),
                )}
              >
                {pct(d.raw_return)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript builds**

```bash
cd web && npm run build 2>&1 | tail -10
```

Expected: DecisionTimeline compiles. The build still fails on `page.tsx` (TickerPriceChart import) — fixed in Task 10.

- [ ] **Step 3: Commit**

```bash
git add web/components/DecisionTimeline.tsx
git commit -m "feat(web): restyle DecisionTimeline to Axiara tokens

Drop inline styles. Tailwind + glass surface + brand-red/green for
positive/negative realized returns. Font-mono tabular-nums for the
date and return columns. Matches the visual language established in
PR #16 + carried through PR #22's auth UI."
```

---

### Task 10: Wire the new component into the page + delete old chart

**Files:**
- Modify: `web/app/portfolio/[ticker]/page.tsx`
- Delete: `web/components/TickerPriceChart.tsx`

- [ ] **Step 1: Replace `page.tsx` contents**

```tsx
// web/app/portfolio/[ticker]/page.tsx
import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import Nav from "@/components/Nav";
import TickerChartWorkspace from "@/components/TickerChartWorkspace";
import DecisionTimeline from "@/components/DecisionTimeline";
import type { TickerDetailOut } from "@/lib/types";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ interval?: string }>;
}

export default async function TickerPage({ params, searchParams }: PageProps) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const { ticker } = await params;
  const { interval: rawInterval } = await searchParams;
  const interval: "1d" | "1h" = rawInterval === "1h" ? "1h" : "1d";

  let detail: TickerDetailOut;
  try {
    detail = await api.portfolioTicker(ticker, interval);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <header className="mb-6 flex flex-wrap items-baseline gap-3 border-b border-border pb-4">
          <h1 className="font-mono text-3xl font-semibold tracking-tight text-fg">
            {detail.ticker}
          </h1>
          <span className="text-sm text-fg-muted">
            {detail.decisions.length} decision{detail.decisions.length === 1 ? "" : "s"}
          </span>
        </header>

        <section className="space-y-6">
          <TickerChartWorkspace
            bars={detail.prices}
            decisions={detail.decisions}
            ticker={detail.ticker}
            interval={interval}
            dataRangeClipped={detail.data_range_clipped}
          />

          <div>
            <h2 className="mb-3 font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">
              Decisions
            </h2>
            <DecisionTimeline decisions={detail.decisions} />
          </div>
        </section>
      </main>
    </>
  );
}
```

- [ ] **Step 2: Update `api.portfolioTicker` to accept interval**

Open `web/lib/api.ts`. The current method:

```typescript
portfolioTicker: (ticker: string) =>
  get<TickerDetailOut>(`/portfolio/ticker/${encodeURIComponent(ticker)}`),
```

Replace with:

```typescript
portfolioTicker: (ticker: string, interval?: "1d" | "1h") => {
  const path = `/portfolio/ticker/${encodeURIComponent(ticker)}`;
  return get<TickerDetailOut>(
    interval && interval !== "1d" ? `${path}?interval=${interval}` : path,
  );
},
```

- [ ] **Step 3: Delete the old chart component**

```bash
rm web/components/TickerPriceChart.tsx
```

- [ ] **Step 4: Verify the full build is clean**

```bash
cd web && npm run build 2>&1 | tail -15
```

Expected: build succeeds, no TypeScript errors, no broken imports. `/portfolio/[ticker]` appears in the route list.

- [ ] **Step 5: Commit**

```bash
git add web/app/portfolio/\[ticker\]/page.tsx web/lib/api.ts
git rm web/components/TickerPriceChart.tsx
git commit -m "feat(web): wire TickerChartWorkspace + DecisionTimeline into ticker page

- page.tsx reads ?interval from searchParams (defaults to 1d), passes
  to api.portfolioTicker(ticker, interval).
- Layout uses Axiara tokens — max-w-7xl, glass header border, mono
  caps eyebrow on the Decisions section.
- Old TickerPriceChart.tsx deleted; no remaining consumers.
- api.portfolioTicker gains an optional interval param that appends
  ?interval= when set to non-default."
```

---

## Phase 5 — E2E tests + ship

### Task 11: Playwright e2e for the new chart

**Files:**
- Create: `web/tests/e2e/ticker-chart.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
// web/tests/e2e/ticker-chart.spec.ts
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/portfolio/[ticker] chart", () => {
  test("renders TickerChartWorkspace with both canvases", async ({ page }) => {
    await signIn(page);
    await page.goto("/history");
    await page.getByText("NVDA").first().click();
    // From /history NVDA row we end up at /history/{runId}; navigate to portfolio explicitly.
    await page.goto("/portfolio/NVDA");

    // Workspace container is present with our data-testid.
    const workspace = page.getByTestId("ticker-chart-workspace");
    await expect(workspace).toBeVisible();

    // Two <canvas> elements: one for the main chart (price+volume), one for RSI.
    await expect(workspace.locator("canvas")).toHaveCount(
      2,
      { timeout: 5000 },
    );

    // Header shows the ticker and indicator legend.
    await expect(workspace.getByText("NVDA")).toBeVisible();
    await expect(workspace.getByText(/sma\(20,50\)/i)).toBeVisible();
    await expect(workspace.getByText(/rsi\(14\)/i)).toBeVisible();
  });

  test("Daily / Hourly toggle updates URL searchParams", async ({ page }) => {
    await signIn(page);
    await page.goto("/portfolio/NVDA");

    // Default = 1d. Click 1H button.
    const hourlyTab = page.getByRole("tab", { name: "1H" });
    await hourlyTab.click();

    await expect(page).toHaveURL(/\?interval=1h/);
    await expect(hourlyTab).toHaveAttribute("aria-selected", "true");

    // Click back to 1D.
    await page.getByRole("tab", { name: "1D" }).click();
    await expect(page).not.toHaveURL(/interval=1h/);
  });

  test("decisions render below the chart in the timeline", async ({ page }) => {
    await signIn(page);
    await page.goto("/portfolio/NVDA");

    // The Decisions section heading.
    await expect(page.getByRole("heading", { name: /^Decisions$/i })).toBeVisible();

    // At least one row in the timeline table for the seeded NVDA fixture.
    const table = page.locator("table").last();
    await expect(table).toBeVisible();
    await expect(table.locator("tbody tr")).not.toHaveCount(0);
  });
});
```

- [ ] **Step 2: Run the e2e**

```bash
cd web && npx playwright test ticker-chart.spec --reporter=line 2>&1 | tail -15
```

Expected: 3 tests pass. If the dev server isn't running locally, see the Phase 6 note — the workflow dispatch in CI exercises the same test suite against the deployed VM, so a local execution failure doesn't block merge.

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/ticker-chart.spec.ts
git commit -m "test(web): Playwright e2e for /portfolio/[ticker] chart

Three tests:
- Workspace container + 2 canvases (price chart + RSI chart) render.
- 1D/1H toggle updates URL searchParams + aria-selected.
- Decisions section heading + at least one row in the timeline table.

Uses the same inline credentials-provider sign-in pattern as
smoke.spec.ts (no global setup or storageState)."
```

---

### Task 12: PR + pre-merge validation + merge + smoke

**Files:** none.

- [ ] **Step 1: Push the branch**

```bash
git push --set-upstream fork feature/technical-chart
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(chart): TradingView lightweight-charts on /portfolio/[ticker]" \
  --base main \
  --head feature/technical-chart \
  --body "$(cat <<'EOF'
## Summary

Wave 4 item 3. Replaces the Recharts daily-close line chart on \`/portfolio/[ticker]\` with a 3-pane TradingView lightweight-charts workspace: candlesticks + SMA(20,50) + EMA(9,21) overlays + decision arrow markers (top), volume histogram (middle), RSI(14) with 30/70 reference lines (bottom). Daily/Hourly timeframe toggle via URL searchParams. DecisionTimeline restyled to Axiara tokens.

Server widens \`PricePoint\` -> \`OHLCVBar\` with O/H/L/V fields; \`fetch_prices()\` accepts \`interval="1d"|"1h"\` and clips hourly to last 60 days (yfinance limit).

## Locked decisions

- Library: **TradingView lightweight-charts** (~40KB gzip, MIT, purpose-built for finance)
- Indicators v1: Volume + SMA(20,50) + EMA(9,21) + RSI(14)
- Timeframes: Daily (default) + Hourly toggle
- Decision overlay: arrow markers on price pane + restyled DecisionTimeline table

## Documented design decisions (spec §6)

- **Vitest** added as a dev dep — pure-function indicator math gets proper unit tests; first vitest in the web/ tree
- **OHLCVBar replaces PricePoint** — schema rename rather than parallel schemas (only one consumer)
- **Interval in URL searchParams** — \`/portfolio/AAPL?interval=1h\` is bookmarkable + reload-stable

## Implementation

- **Server (1 commit)**: schema rename, fetch_prices interval support with cache-key separation, endpoint ?interval validation, 7 new pytest tests.
- **Web infra (3 commits)**: lightweight-charts install, vitest setup, openapi-types regen.
- **Components (4 commits)**: indicator math + 12 vitest tests (TDD), TickerChartWorkspace (two synchronized chart instances), DecisionTimeline restyle, page wire-up + delete old chart.
- **E2E (1 commit)**: 3 Playwright tests covering canvas render, toggle, decisions.

## Test plan

- [x] Server: previous-baseline + 7 pytest tests passing
- [x] Web: 12 vitest indicator tests passing
- [x] \`npm run build\` clean
- [x] 3 new Playwright e2e tests
- [ ] Pre-merge: workflow dispatch against PR branch
- [ ] Post-merge: manual browser smoke on /portfolio/NVDA — verify candles + overlays + markers + volume + RSI + toggle

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Pre-merge workflow dispatch**

```bash
gh workflow run deploy.yml --repo erikgunawans/TradingAgents --ref feature/technical-chart
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: all 3 jobs (Build api, Build web, Deploy to VM) succeed. The deploy step recreates the VM containers with the new server schema (OHLCVBar) and the new web code.

- [ ] **Step 4: Post-deploy smoke (auth.ts unchanged, so OAuth still works)**

```bash
curl -fsS -o /dev/null -w "https://tradix.axiara.ai/login -> %{http_code}\n" https://tradix.axiara.ai/login
curl -fsS https://tradix.axiara.ai/api/auth/providers | python3 -c "import json, sys; print('providers:', list(json.load(sys.stdin).keys()))"
```

Expected: 200, both `github` and `google` providers still present.

- [ ] **Step 5: Merge**

```bash
PR_NUM=$(gh pr list --repo erikgunawans/TradingAgents --head feature/technical-chart --json number --jq '.[0].number')
gh pr merge $PR_NUM --merge --repo erikgunawans/TradingAgents
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: PR merges, auto-deploy on main succeeds.

- [ ] **Step 6: Sync local + cleanup**

```bash
git checkout main && git pull fork main
git branch -d feature/technical-chart
git log --oneline -3
```

- [ ] **Step 7: Manual browser smoke**

Open `https://tradix.axiara.ai/portfolio/NVDA` (signed in). Verify:

1. The TickerChartWorkspace renders with candles + 4 colored MA overlays + green/red volume histogram bars.
2. RSI(14) chart below shows a curve plus dashed horizontal lines at 30 and 70.
3. Decision arrows appear at the dates of past Buy/Hold/Sell decisions on NVDA.
4. Clicking the "1H" toggle navigates to `?interval=1h` and the chart re-renders with hourly bars.
5. DecisionTimeline below the chart uses the new Axiara styling (mono caps headers, green/red return %).

If hourly view shows the "limited to last 60 days" notice, that's expected for NVDA (yfinance limit).

---

## Acceptance criteria

Mapping back to design §10:

- [ ] TickerChartWorkspace renders 3 visual panes → Tasks 8 + 10 + Task 11 e2e.
- [ ] `?interval=1h` switches to hourly → Tasks 3 + 8 + 10 + Task 11 e2e.
- [ ] Hourly with > 60-day range shows the clipping notice → Tasks 3 + 8.
- [ ] SMA(20,50) + EMA(9,21) overlays with distinct colors + legend → Tasks 7 + 8.
- [ ] Volume bars colored green/red per up/down day → Task 8.
- [ ] RSI(14) with 30/70 reference lines → Tasks 7 + 8.
- [ ] Decision markers: up-arrow / down-arrow / circle with rating + return text → Task 8.
- [ ] DecisionTimeline restyled with Tailwind + Axiara, no inline styles → Task 9.
- [ ] Indicator unit tests pass → Tasks 5 + 7.
- [ ] Playwright e2e for chart render + toggle + decisions → Task 11.
- [ ] No regression on empty-data tickers → Task 8 (empty-state branch).
- [ ] `web/components/TickerPriceChart.tsx` deleted, no broken imports → Task 10.

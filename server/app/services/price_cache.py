"""Disk-cached yfinance price fetcher.

Per spec §5.3: yfinance call in the per-ticker request path is slow on cold
cache (1–3s first hit). We cache to a per-user JSON file for 24h.

All filesystem access goes through user_root.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.services.user_root import (
    DATE_RE,
    TICKER_RE,
    check_segment,
)

logger = logging.getLogger(__name__)

Interval = Literal["1d", "1h"]


class PriceFetchError(RuntimeError):
    """Raised when yfinance fails to return usable data."""


def _ttl_seconds() -> int:
    return get_settings().price_cache_ttl_seconds


# Module-level shim around the yfinance call so tests can patch it.
# Keep the import + actual yfinance call internal to this function;
# callers patch `_fetch_yf` rather than monkeypatching yfinance.
async def _fetch_yf(ticker: str, *, start: str, end: str, interval: str):
    """Returns a pandas DataFrame with columns: Open, High, Low, Close, Volume.
    Index is DatetimeIndex (tz-aware UTC for hourly, naive date for daily)."""
    import asyncio

    import yfinance as yf

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: yf.Ticker(ticker).history(
            start=start, end=end, interval=interval, auto_adjust=False
        ),
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

    try:
        df = await _fetch_yf(ticker, start=effective_start, end=end, interval=interval)
    except Exception as exc:  # noqa: BLE001
        raise PriceFetchError(str(exc)) from exc

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

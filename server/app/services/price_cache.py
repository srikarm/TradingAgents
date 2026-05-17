"""Disk-cached yfinance price fetcher.

Per spec §5.3: yfinance call in the per-ticker request path is slow on cold
cache (1–3s first hit). We cache to a per-user JSON file for 24h.

All filesystem access goes through user_root.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from app.services.user_root import (
    DATE_RE,
    TICKER_RE,
    _check_segment,
    user_results_dir,
)


class PriceFetchError(RuntimeError):
    """Raised when yfinance fails to return usable data."""


def _ttl_seconds() -> int:
    return get_settings().price_cache_ttl_seconds


def _cache_path(
    dashboard_dir: Path, user_id: uuid.UUID, ticker: str, start: str, end: str
) -> Path:
    base = user_results_dir(dashboard_dir, str(user_id)) / "cache" / "prices"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{ticker}_{start}_{end}.json"


def _yf_history(symbol: str, start: str, end: str) -> "pd.DataFrame":
    """Indirection so tests can monkeypatch the real yfinance call."""
    import yfinance as yf

    ticker = yf.Ticker(symbol.upper())
    return ticker.history(start=start, end=end)


def _df_to_points(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty or "Close" not in df.columns:
        return []
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    points: list[dict[str, Any]] = []
    for ts, close in df["Close"].items():
        date_str = pd.Timestamp(ts).strftime("%Y-%m-%d")
        try:
            points.append({"trade_date": date_str, "close": round(float(close), 4)})
        except (TypeError, ValueError):
            continue
    return points


async def fetch_prices(
    dashboard_dir: Path,
    *,
    user_id: uuid.UUID,
    ticker: str,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    """Return [{trade_date, close}, ...] for `ticker` from `start` to `end`.

    Caches results to disk under the per-user namespace for `_ttl_seconds()`.
    Raises `PriceFetchError` on yfinance failure. Raises `ValueError` on
    obviously invalid ticker/date inputs (defense-in-depth; route should
    already have validated).
    """
    _check_segment("ticker", ticker, TICKER_RE)
    _check_segment("start", start, DATE_RE)
    _check_segment("end", end, DATE_RE)

    path = _cache_path(dashboard_dir, user_id, ticker, start, end)
    if path.is_file():
        age = time.time() - path.stat().st_mtime
        if age < _ttl_seconds():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass  # fall through to refetch

    try:
        df = _yf_history(ticker.upper(), start, end)
    except Exception as exc:  # noqa: BLE001
        raise PriceFetchError(str(exc)) from exc

    points = _df_to_points(df)
    try:
        path.write_text(json.dumps(points), encoding="utf-8")
    except OSError:
        pass  # cache-write failure is non-fatal
    return points

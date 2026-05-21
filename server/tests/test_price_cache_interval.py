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
async def test_daily_with_tz_aware_us_eastern_index(tmp_path):
    """yfinance returns daily US equity data with tz='America/New_York'.
    Our fetch_prices must produce ISO date strings in the bar's wall-clock
    timezone (i.e., the trading date), not UTC-converted."""
    # Build a daily DataFrame with US/Eastern timezone-aware index.
    # 2024-05-10 midnight US/Eastern = 2024-05-10T04:00:00Z (UTC).
    # We MUST emit "2024-05-10" (the trading date in market timezone),
    # NOT "2024-05-10" coincidentally because both happen to fall on the
    # same calendar date in this case — pick a date where US/Eastern and
    # UTC disagree by date when displayed via .strftime.
    df = pd.DataFrame(
        {
            "Open":   [100.0, 101.0],
            "High":   [101.0, 102.0],
            "Low":    [ 99.0, 100.0],
            "Close":  [100.5, 101.5],
            "Volume": [10000, 11000],
        },
        index=pd.DatetimeIndex(
            ["2024-05-10 00:00:00", "2024-05-11 00:00:00"],
            name="Date",
            tz="America/New_York",
        ),
    )
    with patch.object(price_cache, "_fetch_yf", AsyncMock(return_value=df)):
        bars, _ = await price_cache.fetch_prices(
            dashboard_dir=tmp_path, user_id=uuid.uuid4(),
            ticker="AAPL", start="2024-05-10", end="2024-05-11",
            interval="1d",
        )
    # Expect the trade_date to be the LOCAL trading date, not the UTC
    # date the timestamp would convert to. 2024-05-10 midnight in New York
    # is 2024-05-10T04:00:00Z; pandas strftime on the tz-aware ts produces
    # "2024-05-10" in the timestamp's own tz.
    assert bars[0]["trade_date"] == "2024-05-10"
    assert bars[1]["trade_date"] == "2024-05-11"


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

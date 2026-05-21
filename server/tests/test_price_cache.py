import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from app.services import price_cache
from app.services.price_cache import PriceFetchError, fetch_prices


def _fake_daily_df(rows):
    """Build a DataFrame mimicking yfinance daily history()."""
    idx = pd.DatetimeIndex([d for d, _ in rows], name="Date", tz="UTC")
    closes = [c for _, c in rows]
    return pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": [1000] * len(rows),
    }, index=idx)


@pytest.mark.asyncio
async def test_fetch_prices_writes_cache_and_returns_points(tmp_path):
    uid = uuid.uuid4()

    df = _fake_daily_df([("2024-05-09", 100.0), ("2024-05-10", 102.5)])
    mock = AsyncMock(return_value=df)

    with patch.object(price_cache, "_fetch_yf", mock):
        bars, clipped = await fetch_prices(
            tmp_path, user_id=uid, ticker="NVDA", start="2024-05-09", end="2024-05-10"
        )

    assert clipped is False
    assert len(bars) == 2
    assert bars[0]["trade_date"] == "2024-05-09"
    assert bars[0]["close"] == 100.0
    assert bars[1]["trade_date"] == "2024-05-10"
    assert bars[1]["close"] == 102.5
    assert mock.call_count == 1  # called once

    # Second call returns from cache without invoking yfinance
    with patch.object(price_cache, "_fetch_yf", mock):
        bars2, _ = await fetch_prices(
            tmp_path, user_id=uid, ticker="NVDA", start="2024-05-09", end="2024-05-10"
        )
    assert bars2 == bars
    assert mock.call_count == 1  # still one (cache hit)


@pytest.mark.asyncio
async def test_fetch_prices_re_fetches_after_ttl(tmp_path, monkeypatch):
    uid = uuid.uuid4()

    df = _fake_daily_df([("2024-05-09", 100.0)])
    mock = AsyncMock(return_value=df)
    monkeypatch.setattr(price_cache, "_ttl_seconds", lambda: 0)  # always stale

    with patch.object(price_cache, "_fetch_yf", mock):
        await fetch_prices(tmp_path, user_id=uid, ticker="NVDA",
                           start="2024-05-09", end="2024-05-09")
        await fetch_prices(tmp_path, user_id=uid, ticker="NVDA",
                           start="2024-05-09", end="2024-05-09")

    assert mock.call_count == 2  # both fetches went to yfinance


@pytest.mark.asyncio
async def test_fetch_prices_raises_on_yf_failure(tmp_path):
    uid = uuid.uuid4()

    mock = AsyncMock(side_effect=RuntimeError("yfinance unavailable"))

    with patch.object(price_cache, "_fetch_yf", mock):
        with pytest.raises(PriceFetchError):
            await fetch_prices(
                tmp_path, user_id=uid, ticker="NVDA", start="2024-05-09", end="2024-05-10"
            )


@pytest.mark.asyncio
async def test_fetch_prices_rejects_bad_ticker(tmp_path):
    uid = uuid.uuid4()
    with pytest.raises(ValueError):
        await fetch_prices(
            tmp_path, user_id=uid, ticker="../etc/passwd",
            start="2024-05-09", end="2024-05-10",
        )


@pytest.mark.asyncio
async def test_fetch_prices_isolates_users(tmp_path):
    """Two users requesting the same ticker+range must hit distinct cache paths."""
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()

    df = _fake_daily_df([("2024-05-09", 100.0)])
    mock = AsyncMock(return_value=df)

    with patch.object(price_cache, "_fetch_yf", mock):
        await fetch_prices(
            tmp_path, user_id=uid_a, ticker="NVDA",
            start="2024-05-09", end="2024-05-09",
        )
        # Second user with same args must hit yfinance again — caches are per-user.
        await fetch_prices(
            tmp_path, user_id=uid_b, ticker="NVDA",
            start="2024-05-09", end="2024-05-09",
        )
    assert mock.call_count == 2

    # Cache files live at different paths under each user's namespace.
    cache_a = tmp_path / str(uid_a) / "price-cache" / "NVDA-2024-05-09-2024-05-09-1d.json"
    cache_b = tmp_path / str(uid_b) / "price-cache" / "NVDA-2024-05-09-2024-05-09-1d.json"
    assert cache_a.is_file()
    assert cache_b.is_file()
    assert cache_a != cache_b

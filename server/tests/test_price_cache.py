import uuid
from pathlib import Path

import pandas as pd
import pytest

from app.services import price_cache
from app.services.price_cache import PriceFetchError, fetch_prices


def _fake_df(rows):
    """Build a DataFrame mimicking yfinance.history()'s shape."""
    idx = pd.DatetimeIndex([d for d, _ in rows], name="Date")
    return pd.DataFrame({"Close": [c for _, c in rows]}, index=idx)


@pytest.mark.asyncio
async def test_fetch_prices_writes_cache_and_returns_points(tmp_path, monkeypatch):
    uid = uuid.uuid4()
    calls = []

    def fake_yf(symbol, start, end):
        calls.append((symbol, start, end))
        return _fake_df([("2024-05-09", 100.0), ("2024-05-10", 102.5)])

    monkeypatch.setattr(price_cache, "_yf_history", fake_yf)

    pts = await fetch_prices(
        tmp_path, user_id=uid, ticker="NVDA", start="2024-05-09", end="2024-05-10"
    )

    assert len(pts) == 2
    assert pts[0] == {"trade_date": "2024-05-09", "close": 100.0}
    assert pts[1] == {"trade_date": "2024-05-10", "close": 102.5}
    assert len(calls) == 1  # called once

    # Second call returns from cache without invoking yfinance
    pts2 = await fetch_prices(
        tmp_path, user_id=uid, ticker="NVDA", start="2024-05-09", end="2024-05-10"
    )
    assert pts2 == pts
    assert len(calls) == 1  # still one


@pytest.mark.asyncio
async def test_fetch_prices_re_fetches_after_ttl(tmp_path, monkeypatch):
    uid = uuid.uuid4()
    calls = []

    def fake_yf(symbol, start, end):
        calls.append((symbol, start, end))
        return _fake_df([("2024-05-09", 100.0)])

    monkeypatch.setattr(price_cache, "_yf_history", fake_yf)
    monkeypatch.setattr(price_cache, "_ttl_seconds", lambda: 0)  # always stale

    await fetch_prices(tmp_path, user_id=uid, ticker="NVDA",
                       start="2024-05-09", end="2024-05-09")
    await fetch_prices(tmp_path, user_id=uid, ticker="NVDA",
                       start="2024-05-09", end="2024-05-09")

    assert len(calls) == 2  # both fetches went to yfinance


@pytest.mark.asyncio
async def test_fetch_prices_raises_on_yf_failure(tmp_path, monkeypatch):
    uid = uuid.uuid4()

    def boom(symbol, start, end):
        raise RuntimeError("yfinance unavailable")

    monkeypatch.setattr(price_cache, "_yf_history", boom)

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

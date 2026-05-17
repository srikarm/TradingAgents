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


@pytest.mark.asyncio
async def test_fetch_prices_isolates_users(tmp_path, monkeypatch):
    """Two users requesting the same ticker+range must hit distinct cache
    paths under their own user_root, so one user's cache cannot poison another.
    """
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()

    call_log: list[tuple] = []

    def fake_yf(symbol, start, end):
        call_log.append((symbol, start, end))
        return _fake_df([("2024-05-09", 100.0)])

    monkeypatch.setattr(price_cache, "_yf_history", fake_yf)

    await fetch_prices(
        tmp_path, user_id=uid_a, ticker="NVDA",
        start="2024-05-09", end="2024-05-09",
    )
    # Second user with same args must hit yfinance again — caches are per-user.
    await fetch_prices(
        tmp_path, user_id=uid_b, ticker="NVDA",
        start="2024-05-09", end="2024-05-09",
    )
    assert len(call_log) == 2

    # And the cache files live at different paths under each user's namespace
    cache_a = tmp_path / "users" / str(uid_a) / "cache" / "prices" / "NVDA_2024-05-09_2024-05-09.json"
    cache_b = tmp_path / "users" / str(uid_b) / "cache" / "prices" / "NVDA_2024-05-09_2024-05-09.json"
    assert cache_a.is_file()
    assert cache_b.is_file()
    assert cache_a != cache_b

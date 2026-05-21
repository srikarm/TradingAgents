# server/tests/test_portfolio_ticker_interval.py
"""End-to-end test of /portfolio/ticker/{ticker}?interval=... shape.

The yfinance layer is mocked so the test is deterministic.
Uses the inline client + make_jwt() + authed_user pattern (no shared fixture).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.models.user import User
from app.routers import portfolio as portfolio_router
from app.services import price_cache
from tests.conftest import make_jwt

GITHUB_ID = "test-user-ticker-interval"


@pytest.fixture
def client(db_session, monkeypatch):
    get_settings.cache_clear()

    # Disable per-request mirror sync so tests focus on price/interval logic.
    async def noop(*a, **kw):
        return 0

    monkeypatch.setattr(portfolio_router, "_sync_user", noop)

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


@pytest.fixture
async def authed_user(db_session) -> User:
    u = User(id=uuid.uuid4(), github_id=GITHUB_ID)
    db_session.add(u)
    # Also add a MemoryEntry so the ticker endpoint doesn't 404.
    e = MemoryEntry(
        id=uuid.uuid4(),
        user_id=u.id,
        ticker="AAPL",
        trade_date="2026-05-21",
        rating="Hold",
        status=MemoryEntryStatus.PENDING,
        raw_return=None,
        alpha_return=None,
        holding_days=None,
        decision_text=None,
        reflection_text=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(e)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_endpoint_default_interval_is_1d(client, authed_user):
    """No ?interval query param -> daily bars, OHLCV in response."""
    with patch.object(price_cache, "fetch_prices",
                      AsyncMock(return_value=([{
                          "trade_date": "2026-05-21",
                          "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                          "volume": 10000,
                      }], False))):
        async with client as c:
            res = await c.get(
                "/portfolio/ticker/AAPL",
                headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
            )
    assert res.status_code == 200
    body = res.json()
    assert body["prices"][0]["open"] == 100.0
    assert "data_range_clipped" in body
    assert body["data_range_clipped"] is False


@pytest.mark.asyncio
async def test_endpoint_hourly_returns_clipped_flag(client, authed_user):
    """?interval=1h passes through; clipped flag in response if backend clipped."""
    with patch.object(price_cache, "fetch_prices",
                      AsyncMock(return_value=([{
                          "trade_date": "2026-05-21T14:00:00Z",
                          "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2,
                          "volume": 1000,
                      }], True))):
        async with client as c:
            res = await c.get(
                "/portfolio/ticker/AAPL?interval=1h",
                headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
            )
    assert res.status_code == 200
    body = res.json()
    assert body["prices"][0]["trade_date"] == "2026-05-21T14:00:00Z"
    assert body["data_range_clipped"] is True


@pytest.mark.asyncio
async def test_endpoint_rejects_invalid_interval(client, authed_user):
    """?interval=invalid -> 422."""
    async with client as c:
        res = await c.get(
            "/portfolio/ticker/AAPL?interval=5m",
            headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
        )
    assert res.status_code == 422

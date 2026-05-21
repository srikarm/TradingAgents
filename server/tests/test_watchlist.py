# server/tests/test_watchlist.py
"""End-to-end tests of /watchlist endpoints (CRUD + scoping).

Fixture choice: `async_client_authed` and `authed_user` are defined inline
here (not in conftest.py) following the precedent set by
`test_runs_active_count.py` (Wave 4 item 2). The shared conftest provides
only `db_session` and `make_jwt`; per-test-file fixtures inline the
`get_db` override + bearer-token client wrapper.
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.user import User
from app.models.watchlist import WatchlistItem
from tests.conftest import make_jwt

GITHUB_ID = "test-user-watchlist"


@pytest_asyncio.fixture
async def authed_user(db_session) -> User:
    """Pre-create the user that the bearer JWT will resolve to."""
    u = User(id=uuid.uuid4(), github_id=GITHUB_ID)
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def async_client_authed(db_session, authed_user):
    """An httpx AsyncClient with Authorization header pre-set."""
    # Clear LRU cache so stale NEXTAUTH_SECRET from prior tests doesn't bleed in.
    get_settings.cache_clear()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    token = make_jwt(GITHUB_ID)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_empty_list_for_new_user(async_client_authed):
    """GET /watchlist returns [] for a user with no rows."""
    res = await async_client_authed.get("/watchlist")
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_add_ticker_returns_201_and_row(async_client_authed):
    """POST /watchlist {ticker} returns 201 + persisted row."""
    res = await async_client_authed.post(
        "/watchlist", json={"ticker": "AAPL", "notes": "tracking earnings"}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["notes"] == "tracking earnings"
    assert "id" in body
    assert "added_at" in body


@pytest.mark.asyncio
async def test_add_without_notes_succeeds(async_client_authed):
    """POST /watchlist with notes omitted → notes is null in response."""
    res = await async_client_authed.post("/watchlist", json={"ticker": "MSFT"})
    assert res.status_code == 201
    assert res.json()["notes"] is None


@pytest.mark.asyncio
async def test_duplicate_returns_409(async_client_authed):
    """POST /watchlist with a ticker already present → 409."""
    await async_client_authed.post("/watchlist", json={"ticker": "GOOG"})
    res = await async_client_authed.post(
        "/watchlist", json={"ticker": "GOOG", "notes": "second attempt"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "ticker already on watchlist"


@pytest.mark.asyncio
async def test_lowercase_ticker_returns_422(async_client_authed):
    """POST /watchlist with lowercase ticker → 422 (TICKER_RE rejects)."""
    res = await async_client_authed.post("/watchlist", json={"ticker": "aapl"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invalid_ticker_too_long_returns_422(async_client_authed):
    """POST /watchlist with a 13-char ticker → 422."""
    res = await async_client_authed.post(
        "/watchlist", json={"ticker": "ABCDEFGHIJKLM"}  # 13 chars, TICKER_RE max is 12
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_list_returns_most_recent_first(async_client_authed):
    """GET /watchlist orders by added_at DESC."""
    for ticker in ["AAA", "BBB", "CCC"]:
        await async_client_authed.post("/watchlist", json={"ticker": ticker})
    res = await async_client_authed.get("/watchlist")
    tickers = [item["ticker"] for item in res.json()]
    assert tickers == ["CCC", "BBB", "AAA"]  # most-recent-added first


@pytest.mark.asyncio
async def test_patch_updates_notes(async_client_authed):
    """PATCH /watchlist/{ticker} {notes} replaces notes."""
    await async_client_authed.post(
        "/watchlist", json={"ticker": "TSLA", "notes": "old note"}
    )
    res = await async_client_authed.patch(
        "/watchlist/TSLA", json={"notes": "new thesis"}
    )
    assert res.status_code == 200
    assert res.json()["notes"] == "new thesis"


@pytest.mark.asyncio
async def test_patch_missing_ticker_returns_404(async_client_authed):
    """PATCH /watchlist/{ticker} for unknown ticker → 404."""
    res = await async_client_authed.patch(
        "/watchlist/NEVER", json={"notes": "anything"}
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_row(async_client_authed):
    """DELETE /watchlist/{ticker} → 204 and the row is gone."""
    await async_client_authed.post("/watchlist", json={"ticker": "NVDA"})
    res = await async_client_authed.delete("/watchlist/NVDA")
    assert res.status_code == 204
    list_res = await async_client_authed.get("/watchlist")
    assert list_res.json() == []


@pytest.mark.asyncio
async def test_delete_missing_ticker_returns_404(async_client_authed):
    """DELETE /watchlist/{ticker} for unknown ticker → 404."""
    res = await async_client_authed.delete("/watchlist/NEVER")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_scoped_to_current_user(async_client_authed, db_session, authed_user):
    """Another user's watchlist rows are invisible — current user sees only their own."""
    other = User(id=uuid.uuid4(), github_id="other-user-999", email=None)
    db_session.add(other)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=other.id, ticker="OTHER"))
    await db_session.flush()
    # Current user adds their own ticker:
    await async_client_authed.post("/watchlist", json={"ticker": "OWN"})

    res = await async_client_authed.get("/watchlist")
    tickers = [item["ticker"] for item in res.json()]
    assert tickers == ["OWN"], "other user's ticker should not leak"

# server/tests/test_watchlist.py
"""End-to-end tests of /watchlist endpoints (CRUD + scoping).

`async_client_authed` and `authed_user` are inlined here (not in conftest.py)
because they bind a test-file-specific JWT subject; the shared conftest
provides only `db_session` and `make_jwt`.
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

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
    """An httpx AsyncClient with Authorization header pre-set.

    `get_db` is overridden to yield a NEW session per request, bound to the
    same engine as `db_session`. This mirrors production semantics (session
    closed and rolled-back if not committed) — critical for the
    persistence test, which would otherwise pass even when the router skips
    `db.commit()`, because a shared session keeps uncommitted writes visible
    until fixture teardown.

    The `authed_user` row created by the `authed_user` fixture must be
    visible to the request session — that's why we commit it before any
    request runs.
    """
    # Clear LRU cache so stale NEXTAUTH_SECRET from prior tests doesn't bleed in.
    get_settings.cache_clear()

    # Make sure the authed_user row is committed so the per-request session
    # can resolve it via get_current_user.
    await db_session.commit()

    request_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def _override_db():
        async with request_factory() as s:
            yield s

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
async def test_add_persists_across_sessions(
    async_client_authed, db_session, authed_user
):
    """POST writes survive session close — guards against missing-commit regressions.

    Without `await db.commit()` in the router, the flushed row is rolled back
    when the per-request session closes. A fresh session opened on the same
    engine would then see no row, even though the HTTP response was 201.
    """
    res = await async_client_authed.post("/watchlist", json={"ticker": "PERSIST"})
    assert res.status_code == 201

    # Open a fresh session bound to the SAME engine used by db_session.
    # We can't use app.db.get_session_factory() because that builds a new
    # engine from settings (a different :memory: DB). db_session.bind is
    # the test fixture's engine — which is what the dependency override
    # routes the router's writes through.
    fresh_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with fresh_factory() as fresh:
        row = (
            await fresh.execute(
                select(WatchlistItem).where(
                    WatchlistItem.user_id == authed_user.id,
                    WatchlistItem.ticker == "PERSIST",
                )
            )
        ).scalar_one_or_none()
        assert row is not None, "POST returned 201 but the row was not committed"


@pytest.mark.asyncio
async def test_scoped_to_current_user(async_client_authed, db_session, authed_user):
    """Another user's watchlist rows are invisible — current user sees only their own."""
    other = User(id=uuid.uuid4(), github_id="other-user-999")
    db_session.add(other)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=other.id, ticker="OTHER"))
    await db_session.commit()
    # Current user adds their own ticker:
    await async_client_authed.post("/watchlist", json={"ticker": "OWN"})

    res = await async_client_authed.get("/watchlist")
    tickers = [item["ticker"] for item in res.json()]
    assert tickers == ["OWN"], "other user's ticker should not leak"

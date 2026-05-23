# server/tests/test_signals_today.py
"""GET /signals/today — daily monitor briefing feed.

`async_client_authed` and `authed_user` are inlined here (not in conftest.py)
because they bind a test-file-specific JWT subject; the shared conftest
provides only `db_session` and `make_jwt`. This mirrors the pattern set in
test_watchlist.py (Wave 5.1) and test_me_monitor_endpoint.py (Wave 5.2).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.run import Run, RunStatus
from app.models.user import User
from app.models.watchlist import WatchlistItem
from tests.conftest import make_jwt

GITHUB_ID = "test-user-signals"


@pytest_asyncio.fixture
async def authed_user(db_session) -> User:
    """Pre-create the user that the bearer JWT will resolve to.

    Defaults: monitor_enabled=False, briefing_tz=None (unconfigured).
    Individual tests mutate the fields they need.
    """
    u = User(id=uuid.uuid4(), github_id=GITHUB_ID)
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def async_client_authed(db_session, authed_user):
    """An httpx AsyncClient with Authorization header pre-set.

    `get_db` is overridden to yield a NEW session per request, bound to the
    same engine as `db_session` (mirrors production session lifecycle).
    """
    get_settings.cache_clear()

    # Commit the authed_user (and any test-scoped seed data already added
    # to db_session) so the per-request session can see them.
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


def _today_in_tz(tz_name: str) -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(timezone.utc).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def _yesterday_in_tz(tz_name: str) -> str:
    from zoneinfo import ZoneInfo
    return (datetime.now(timezone.utc).astimezone(ZoneInfo(tz_name)) - timedelta(days=1)).strftime("%Y-%m-%d")


def _seed_run(db_session, user_id, ticker, trade_date, *, rating=None, status=RunStatus.QUEUED, triggered_by="monitor"):
    run = Run(
        id=uuid.uuid4(), user_id=user_id, ticker=ticker, trade_date=trade_date,
        status=status, final_rating=rating, results_path=f"/tmp/{ticker}",
        triggered_by=triggered_by,
    )
    db_session.add(run)
    return run


@pytest.mark.asyncio
async def test_unconfigured_user_returns_empty(async_client_authed, authed_user, db_session):
    """User with briefing_tz=None → 200, items=[], trade_date=null."""
    # authed_user fixture defaults: monitor_enabled=False, briefing_tz=None
    res = await async_client_authed.get("/signals/today")
    assert res.status_code == 200
    assert res.json() == {"items": [], "trade_date": None}


@pytest.mark.asyncio
async def test_monitor_on_no_signals_returns_empty_with_date(async_client_authed, authed_user, db_session):
    """Monitor on but no monitor runs today → 200, items=[], trade_date=<today>."""
    authed_user.monitor_enabled = True
    authed_user.briefing_tz = "Asia/Jakarta"
    authed_user.briefing_time_local = "07:00"
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["trade_date"] == _today_in_tz("Asia/Jakarta")


@pytest.mark.asyncio
async def test_single_buy_signal(async_client_authed, authed_user, db_session):
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "BBCA.JK", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "BBCA.JK"
    assert items[0]["final_rating"] == "BUY"


@pytest.mark.asyncio
async def test_ranking_buy_sell_inflight_hold(async_client_authed, authed_user, db_session):
    """4 seeded runs (HOLD, SELL, in-flight, BUY) → ordered [BUY, SELL, in-flight, HOLD]."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "HOLDX", today, rating="HOLD", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "SELLX", today, rating="SELL", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "FLIGHT", today, rating=None, status=RunStatus.RUNNING)
    _seed_run(db_session, authed_user.id, "BUYX", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    items = res.json()["items"]
    assert [i["ticker"] for i in items] == ["BUYX", "SELLX", "FLIGHT", "HOLDX"]


@pytest.mark.asyncio
async def test_failed_at_bottom(async_client_authed, authed_user, db_session):
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "BUYX", today, rating="BUY", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "FAILX", today, rating=None, status=RunStatus.FAILED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    items = res.json()["items"]
    assert [i["ticker"] for i in items] == ["BUYX", "FAILX"]


@pytest.mark.asyncio
async def test_manual_runs_filtered(async_client_authed, authed_user, db_session):
    """Manual run NOT in feed; only monitor runs."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "MONX", today, rating="BUY", status=RunStatus.SUCCEEDED, triggered_by="monitor")
    _seed_run(db_session, authed_user.id, "MANX", today, rating="BUY", status=RunStatus.SUCCEEDED, triggered_by="manual")
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert "MONX" in tickers and "MANX" not in tickers


@pytest.mark.asyncio
async def test_yesterday_filtered(async_client_authed, authed_user, db_session):
    """Yesterday's monitor run NOT in feed."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    yesterday = _yesterday_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "TODAY", today, rating="BUY", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "YEST", yesterday, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert tickers == ["TODAY"]


@pytest.mark.asyncio
async def test_other_user_signals_not_leaked(async_client_authed, authed_user, db_session):
    """Another user's monitor signal does NOT appear."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    other = User(id=uuid.uuid4(), github_id="other-monitor", monitor_enabled=True, briefing_tz="Asia/Jakarta")
    db_session.add(other)
    _seed_run(db_session, other.id, "LEAK", today, rating="BUY", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "OWN", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert tickers == ["OWN"]


@pytest.mark.asyncio
async def test_notes_joined_when_present(async_client_authed, authed_user, db_session):
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    db_session.add(WatchlistItem(
        id=uuid.uuid4(), user_id=authed_user.id, ticker="BBCA.JK", notes="tracking earnings",
    ))
    _seed_run(db_session, authed_user.id, "BBCA.JK", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.json()["items"][0]["notes"] == "tracking earnings"


@pytest.mark.asyncio
async def test_notes_null_when_ticker_unwatchlisted(async_client_authed, authed_user, db_session):
    """LEFT JOIN: signal exists, ticker not on watchlist → notes is null."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "ORPHAN", today, rating="BUY", status=RunStatus.SUCCEEDED)
    # NO WatchlistItem for ORPHAN
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "ORPHAN"
    assert items[0]["notes"] is None


@pytest.mark.asyncio
async def test_trade_date_reflects_user_tz(async_client_authed, authed_user, db_session):
    """trade_date in response is computed in user's TZ, not UTC."""
    authed_user.briefing_tz = "Asia/Jakarta"
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    expected = _today_in_tz("Asia/Jakarta")
    assert res.json()["trade_date"] == expected


@pytest.mark.asyncio
async def test_tz_none_returns_trade_date_null(async_client_authed, authed_user, db_session):
    """briefing_tz=None → trade_date in response is null."""
    authed_user.briefing_tz = None
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.json()["trade_date"] is None


@pytest.mark.asyncio
async def test_inflight_ordered_above_hold(async_client_authed, authed_user, db_session):
    """Explicit assertion: null final_rating sits above HOLD."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "HOLDX", today, rating="HOLD", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "FLIGHT", today, rating=None, status=RunStatus.RUNNING)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert tickers == ["FLIGHT", "HOLDX"]

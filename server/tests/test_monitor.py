# server/tests/test_monitor.py
"""Tests for the Wave 5.2 Monitor — daily cron + due-users + dispatch loop."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.user import User
from app.models.run import Run, RunStatus
from app.models.watchlist import WatchlistItem
from app.services.monitor import (
    find_due_users,
    dispatch_user_watchlist,
)
from tests.conftest import make_jwt


GITHUB_ID = "test-user-monitor"


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

    Mirrors the Wave 5.1 watchlist fixture pattern: a NEW per-request session
    bound to the same engine as db_session, so the persistence test can
    catch missing-commit regressions.
    """
    get_settings.cache_clear()
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


def _make_user(github_id: str, *, enabled: bool, time_local: str | None, tz: str | None) -> User:
    return User(
        id=uuid.uuid4(),
        github_id=github_id,
        monitor_enabled=enabled,
        briefing_time_local=time_local,
        briefing_tz=tz,
    )


@pytest.mark.asyncio
async def test_find_due_users_jakarta_at_briefing(db_session):
    """User at 07:00 Asia/Jakarta, tick at 00:00 UTC (= 07:00 WIB) → due."""
    u = _make_user("u-jakarta", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert [x.id for x in due] == [u.id]


@pytest.mark.asyncio
async def test_find_due_users_within_window(db_session):
    """Tick at 00:14 UTC (still in 15-min window after 07:00 WIB briefing) → due."""
    u = _make_user("u-jakarta-2", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 14, 59, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_just_past_window(db_session):
    """Tick at 00:15 UTC → window has passed, NOT due."""
    u = _make_user("u-jakarta-3", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 15, 1, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_before_briefing(db_session):
    """Tick at 23:45 UTC (= 06:45 WIB next day) — window ends 1 min before briefing → NOT due."""
    u = _make_user("u-jakarta-4", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 23, 45, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_disabled_user(db_session):
    """monitor_enabled=False → NOT due regardless of time match."""
    u = _make_user("u-off", enabled=False, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_null_tz(db_session):
    """briefing_tz=None → NOT due (incomplete config)."""
    u = _make_user("u-no-tz", enabled=True, time_local="07:00", tz=None)
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_null_time(db_session):
    """briefing_time_local=None → NOT due."""
    u = _make_user("u-no-time", enabled=True, time_local=None, tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_dst_spring_forward(db_session):
    """US/Eastern DST spring-forward 2026-03-08: 02:00-03:00 EST is skipped.
    A 02:30 briefing on that day resolves via zoneinfo to the post-transition
    equivalent without crashing."""
    u = _make_user("u-dst", enabled=True, time_local="02:30", tz="US/Eastern")
    db_session.add(u)
    await db_session.commit()
    # 06:30 UTC on 2026-03-08 is 02:30 EST — but DST skipped 02:00-03:00, so
    # that local time becomes 03:30 EDT. The function should not raise.
    now_utc = datetime(2026, 3, 8, 6, 30, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)  # should not raise
    # We accept either due=True (zoneinfo resolves to post-transition) or due=False;
    # the contract is: no exception.
    assert isinstance(due, list)


@pytest.mark.asyncio
async def test_find_due_users_two_users_only_one_due(db_session):
    """Two users in different TZs, only one in window."""
    a = _make_user("u-a", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    b = _make_user("u-b", enabled=True, time_local="07:00", tz="America/New_York")
    db_session.add_all([a, b])
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)  # 07:00 WIB; 20:00 prev day NYC
    due_ids = [x.id for x in await find_due_users(db_session, now_utc)]
    assert a.id in due_ids
    assert b.id not in due_ids


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_three_tickers(db_session, monkeypatch):
    """3 watchlist tickers, no prior runs → 3 Run rows, all triggered_by='monitor', QUEUED."""
    u = _make_user("u-disp", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    for t in ["AAPL", "MSFT", "GOOG"]:
        db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker=t))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result == {"dispatched": 3, "skipped_dup": 0, "failed": 0}

    runs = (await db_session.execute(
        select(Run).where(Run.user_id == u.id)
    )).scalars().all()
    assert len(runs) == 3
    assert all(r.triggered_by == "monitor" for r in runs)
    assert all(r.status == RunStatus.QUEUED for r in runs)
    assert mock_pool.enqueue_job.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_skips_existing(db_session, monkeypatch):
    """Manual run already exists for ticker — DuplicateRunningError caught silently."""
    u = _make_user("u-dup", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="AAPL"))
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="MSFT"))
    # Existing QUEUED run for AAPL today (trade_date "2026-05-22" in Asia/Jakarta).
    db_session.add(Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date="2026-05-22",
        status=RunStatus.QUEUED, results_path="/tmp/x",
        triggered_by="manual",
    ))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result == {"dispatched": 1, "skipped_dup": 1, "failed": 0}


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_empty(db_session, monkeypatch):
    """User with empty watchlist → no errors, no rows."""
    u = _make_user("u-empty", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()

    mock_pool = AsyncMock()
    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result == {"dispatched": 0, "skipped_dup": 0, "failed": 0}


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_enqueue_fails(db_session, monkeypatch):
    """arq enqueue raises → run row marked FAILED, loop continues."""
    u = _make_user("u-fail", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="BAD"))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result["failed"] == 1
    failed = (await db_session.execute(
        select(Run).where(Run.user_id == u.id)
    )).scalar_one()
    assert failed.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_triggered_by_default_is_manual(db_session):
    """Existing Run rows (created via the runs router) get triggered_by='manual'."""
    u = _make_user("u-tr", enabled=False, time_local=None, tz=None)
    db_session.add(u)
    await db_session.commit()
    run = Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date="2026-05-22",
        status=RunStatus.QUEUED, results_path="/tmp/x",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.triggered_by == "manual"


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_trade_date_in_user_tz(db_session, monkeypatch):
    """trade_date reflects USER's TZ date, not UTC date."""
    # 22:00 UTC on 2026-05-22 == 05:00 WIB on 2026-05-23. User in Jakarta should
    # get trade_date="2026-05-23".
    u = _make_user("u-tz-date", enabled=True, time_local="05:00", tz="Asia/Jakarta")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="AAPL"))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 22, 0, 0, tzinfo=timezone.utc)
    )
    run = (await db_session.execute(select(Run).where(Run.user_id == u.id))).scalar_one()
    assert run.trade_date == "2026-05-23"


@pytest.mark.asyncio
async def test_dispatch_persists_across_sessions(async_client_authed, authed_user, db_session):
    """Monitor-dispatched run survives session close (guards against missing-commit regressions)."""
    # This test mirrors the pattern from Wave 5.1 — open a fresh session after the dispatch
    # and confirm the row exists. It's the same anti-pattern guard as test_add_persists_across_sessions
    # in test_watchlist.py.
    # (Implementation detail: use async_sessionmaker(db_session.bind) to open a fresh session.)
    from sqlalchemy.ext.asyncio import async_sessionmaker
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=authed_user.id, ticker="PERSIST"))
    authed_user.monitor_enabled = True
    authed_user.briefing_time_local = "07:00"
    authed_user.briefing_tz = "Asia/Jakarta"
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    await dispatch_user_watchlist(
        db_session, mock_pool, authed_user,
        datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc),
    )

    fresh_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with fresh_factory() as fresh:
        row = (await fresh.execute(
            select(Run).where(Run.user_id == authed_user.id, Run.ticker == "PERSIST")
        )).scalar_one_or_none()
        assert row is not None, "dispatch should persist across sessions"
        assert row.triggered_by == "monitor"

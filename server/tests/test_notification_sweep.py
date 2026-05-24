"""Wave 5.4 — batch marker at dispatch + notification_sweep delivery cron.

The sweep's load-bearing property: it fires a digest only once a batch is
*provably* complete (terminal_count == expected_count from the monitor_batches
marker), never on the vacuously-true "zero non-terminal runs" state. These
tests pin that the partial/premature case writes no row, so a late actionable
signal can never be suppressed by an early skip.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.models.notification import MonitorBatch, Notification, NotificationStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.services import notifications as notif_mod
from app.services.monitor import dispatch_user_watchlist

DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # within the sweep's 3-day window


def _enabled_user(gh="sweep-user", email="t@example.com"):
    # briefing_tz=UTC so the sweep's "current local day" equals DATE (UTC today)
    # regardless of the wall-clock TZ the test runs in.
    return User(
        id=uuid.uuid4(), github_id=gh, email=email,
        notify_enabled=True, notify_channel="email", notify_threshold="BUY,SELL",
        monitor_enabled=True, briefing_time_local="07:00", briefing_tz="UTC",
    )


def _run(user_id, ticker, *, status=RunStatus.SUCCEEDED, rating="BUY"):
    return Run(
        id=uuid.uuid4(), user_id=user_id, ticker=ticker, trade_date=DATE,
        status=status, final_rating=rating, results_path="/tmp/x",
        triggered_by="monitor",
    )


def _patch_factory(monkeypatch, db_session):
    class _CM:
        async def __aenter__(self):
            return db_session
        async def __aexit__(self, *e):
            return False

    def fake_get_session_factory():
        return lambda: _CM()

    get_settings.cache_clear()
    monkeypatch.setattr(notif_mod, "get_session_factory", fake_get_session_factory)


async def _count_notifs(db_session, user_id=None):
    stmt = select(func.count()).select_from(Notification)
    if user_id is not None:
        stmt = stmt.where(Notification.user_id == user_id)
    return (await db_session.execute(stmt)).scalar_one()


# ---- batch marker at dispatch (ISC-35 wiring) ----

@pytest.mark.asyncio
async def test_dispatch_writes_batch_marker(db_session):
    """ISC-35 — dispatch records expected_count = number of watchlist tickers."""
    u = _enabled_user("batch-marker")
    db_session.add(u)
    for t in ["AAPL", "MSFT", "GOOG"]:
        db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker=t))
    await db_session.commit()

    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=None)
    await dispatch_user_watchlist(db_session, pool, u, datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc))

    batch = (await db_session.execute(
        select(MonitorBatch).where(MonitorBatch.user_id == u.id)
    )).scalar_one()
    assert batch.expected_count == 3


@pytest.mark.asyncio
async def test_batch_expected_count_excludes_manual_collision(db_session, monkeypatch):
    """Forge HIGH regression — a ticker colliding with a pre-existing MANUAL run
    produces no monitor row, so expected_count must reflect only the realized
    monitor runs. Otherwise terminal_count could never reach an over-optimistic
    expected_count and the digest would silently never fire.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    u = _enabled_user("collision")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="AAPL"))
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="MSFT"))
    # Pre-existing MANUAL run for AAPL today → dispatch will skip it (dup).
    db_session.add(Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date=today,
        status=RunStatus.QUEUED, results_path="/tmp/x", triggered_by="manual",
    ))
    await db_session.commit()

    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=None)
    result = await dispatch_user_watchlist(db_session, pool, u, datetime.now(timezone.utc))
    assert result == {"dispatched": 1, "skipped_dup": 1, "failed": 0}

    batch = (await db_session.execute(
        select(MonitorBatch).where(MonitorBatch.user_id == u.id)
    )).scalar_one()
    # expected_count = 1 (only MSFT got a monitor row), NOT 2 (the ticker count).
    assert batch.expected_count == 1

    # Complete MSFT's monitor run → batch is provably complete → sweep delivers.
    msft = (await db_session.execute(
        select(Run).where(Run.user_id == u.id, Run.ticker == "MSFT", Run.triggered_by == "monitor")
    )).scalar_one()
    msft.status = RunStatus.SUCCEEDED
    msft.final_rating = "BUY"
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    sweep = await notif_mod.notification_sweep({})
    assert sweep["sent"] == 1


@pytest.mark.asyncio
async def test_dispatch_empty_watchlist_no_batch(db_session):
    u = _enabled_user("batch-empty")
    db_session.add(u)
    await db_session.commit()
    pool = AsyncMock()
    await dispatch_user_watchlist(db_session, pool, u, datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc))
    count = (await db_session.execute(
        select(func.count()).select_from(MonitorBatch)
    )).scalar_one()
    assert count == 0


# ---- sweep delivery ----

@pytest.mark.asyncio
async def test_sweep_sends_when_batch_complete(db_session, monkeypatch):
    u = _enabled_user("complete")
    db_session.add(u)
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=u.id, trade_date=DATE, expected_count=2))
    db_session.add(_run(u.id, "AAPL", rating="BUY"))
    db_session.add(_run(u.id, "MSFT", rating="HOLD"))
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    result = await notif_mod.notification_sweep({})
    assert result["sent"] == 1
    notif = (await db_session.execute(select(Notification).where(Notification.user_id == u.id))).scalar_one()
    assert notif.status == NotificationStatus.SENT.value


@pytest.mark.asyncio
async def test_sweep_skips_partial_batch(db_session, monkeypatch):
    """ISC-36 — expected 3, only 2 terminal → no row written (try later)."""
    u = _enabled_user("partial")
    db_session.add(u)
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=u.id, trade_date=DATE, expected_count=3))
    db_session.add(_run(u.id, "AAPL", rating="BUY"))
    db_session.add(_run(u.id, "MSFT", rating="HOLD"))
    # 3rd run still RUNNING (non-terminal)
    db_session.add(_run(u.id, "GOOG", status=RunStatus.RUNNING, rating=None))
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    result = await notif_mod.notification_sweep({})
    assert result == {"sent": 0, "skipped": 0}
    assert await _count_notifs(db_session, u.id) == 0


@pytest.mark.asyncio
async def test_sweep_premature_cannot_suppress_late_signal(db_session, monkeypatch):
    """ISC-37 — a partial batch writes no skip row, so a BUY landing later still sends."""
    u = _enabled_user("late-buy")
    db_session.add(u)
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=u.id, trade_date=DATE, expected_count=2))
    # First only a HOLD has completed; the BUY is still running.
    db_session.add(_run(u.id, "AAPL", rating="HOLD"))
    running = _run(u.id, "NVDA", status=RunStatus.RUNNING, rating=None)
    db_session.add(running)
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    first = await notif_mod.notification_sweep({})
    assert first == {"sent": 0, "skipped": 0}
    assert await _count_notifs(db_session, u.id) == 0  # no premature skip row

    # Now the BUY completes → batch is provably complete → it must send.
    running.status = RunStatus.SUCCEEDED
    running.final_rating = "BUY"
    await db_session.commit()
    second = await notif_mod.notification_sweep({})
    assert second["sent"] == 1
    notif = (await db_session.execute(select(Notification).where(Notification.user_id == u.id))).scalar_one()
    assert notif.status == NotificationStatus.SENT.value


@pytest.mark.asyncio
async def test_sweep_is_idempotent(db_session, monkeypatch):
    """ISC-24 — a second sweep tick produces no duplicate delivery."""
    u = _enabled_user("idem")
    db_session.add(u)
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=u.id, trade_date=DATE, expected_count=1))
    db_session.add(_run(u.id, "AAPL", rating="BUY"))
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    first = await notif_mod.notification_sweep({})
    second = await notif_mod.notification_sweep({})
    assert first["sent"] == 1
    assert second == {"sent": 0, "skipped": 0}
    assert await _count_notifs(db_session, u.id) == 1


@pytest.mark.asyncio
async def test_sweep_quiet_day_records_skip(db_session, monkeypatch):
    """ISC-19 — complete batch, all HOLD → one skipped_no_signal row, no send."""
    u = _enabled_user("quiet")
    db_session.add(u)
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=u.id, trade_date=DATE, expected_count=2))
    db_session.add(_run(u.id, "AAPL", rating="HOLD"))
    db_session.add(_run(u.id, "MSFT", rating="HOLD"))
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    result = await notif_mod.notification_sweep({})
    assert result["skipped"] == 1
    notif = (await db_session.execute(select(Notification).where(Notification.user_id == u.id))).scalar_one()
    assert notif.status == NotificationStatus.SKIPPED_NO_SIGNAL.value


@pytest.mark.asyncio
async def test_sweep_ignores_prior_day_batch(db_session, monkeypatch):
    """ISC-23 — enabling notify must not retroactively fire for older days.

    A complete, actionable batch dated yesterday is never delivered: the sweep
    only acts on the user's current local day.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    u = _enabled_user("prior-day")
    db_session.add(u)
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=u.id, trade_date=yesterday, expected_count=1))
    db_session.add(Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date=yesterday,
        status=RunStatus.SUCCEEDED, final_rating="BUY", results_path="/tmp/x",
        triggered_by="monitor",
    ))
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    result = await notif_mod.notification_sweep({})
    assert result == {"sent": 0, "skipped": 0}
    assert await _count_notifs(db_session, u.id) == 0


@pytest.mark.asyncio
async def test_sweep_no_batch_means_manual_runs_never_notify(db_session, monkeypatch):
    """ISC-20 — manual runs create no monitor_batch, so the sweep never fires."""
    u = _enabled_user("manual-only")
    db_session.add(u)
    manual = Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date=DATE,
        status=RunStatus.SUCCEEDED, final_rating="BUY", results_path="/tmp/x",
        triggered_by="manual",
    )
    db_session.add(manual)
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    result = await notif_mod.notification_sweep({})
    assert result == {"sent": 0, "skipped": 0}
    assert await _count_notifs(db_session) == 0


@pytest.mark.asyncio
async def test_sweep_cross_user_isolation(db_session, monkeypatch):
    """ISC-21 — each user's digest reflects only their own runs."""
    a = _enabled_user("iso-a", email="a@example.com")
    b = _enabled_user("iso-b", email="b@example.com")
    db_session.add_all([a, b])
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=a.id, trade_date=DATE, expected_count=1))
    db_session.add(MonitorBatch(id=uuid.uuid4(), user_id=b.id, trade_date=DATE, expected_count=1))
    db_session.add(_run(a.id, "AAPL", rating="BUY"))   # A actionable
    db_session.add(_run(b.id, "MSFT", rating="HOLD"))  # B quiet
    await db_session.commit()

    _patch_factory(monkeypatch, db_session)
    result = await notif_mod.notification_sweep({})
    assert result == {"sent": 1, "skipped": 1}
    a_notif = (await db_session.execute(select(Notification).where(Notification.user_id == a.id))).scalar_one()
    b_notif = (await db_session.execute(select(Notification).where(Notification.user_id == b.id))).scalar_one()
    assert a_notif.status == NotificationStatus.SENT.value
    assert b_notif.status == NotificationStatus.SKIPPED_NO_SIGNAL.value

"""Wave 5.4 — notification service: should_notify, digest, claim-first delivery."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import get_settings
from app.models.notification import Notification, NotificationStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.services import notifications as notif_mod
from app.services.notifications import (
    actionable_runs,
    build_digest,
    deliver_for_batch,
    parse_threshold,
    should_notify,
)

DATE = "2026-05-22"


def _run(user_id, ticker, *, status=RunStatus.SUCCEEDED, rating="BUY", trade_date=DATE):
    return Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=trade_date,
        status=status,
        final_rating=rating,
        results_path="/tmp/x",
        triggered_by="monitor",
    )


@pytest_asyncio.fixture
async def user(db_session) -> User:
    u = User(
        id=uuid.uuid4(),
        github_id="svc-user",
        email="trader@example.com",
        notify_enabled=True,
        notify_channel="email",
        notify_threshold="BUY,SELL",
    )
    db_session.add(u)
    await db_session.commit()
    return u


# ---- pure logic ----

def test_parse_threshold():
    assert parse_threshold("BUY,SELL") == {"BUY", "SELL"}
    assert parse_threshold(" BUY , HOLD ") == {"BUY", "HOLD"}
    assert parse_threshold("") == set()


def test_should_notify_true_on_actionable():
    uid = uuid.uuid4()
    runs = [_run(uid, "AAPL", rating="BUY"), _run(uid, "MSFT", rating="HOLD")]
    assert should_notify(runs, {"BUY", "SELL"}) is True


def test_should_notify_false_on_quiet_day():
    """ISC-12 — every run HOLD/None/FAILED → no notification."""
    uid = uuid.uuid4()
    runs = [
        _run(uid, "AAPL", rating="HOLD"),
        _run(uid, "MSFT", rating=None),
        _run(uid, "GOOG", status=RunStatus.FAILED, rating=None),
    ]
    assert should_notify(runs, {"BUY", "SELL"}) is False


def test_actionable_excludes_failed_even_if_rating_set():
    uid = uuid.uuid4()
    runs = [_run(uid, "AAPL", status=RunStatus.FAILED, rating="BUY")]
    assert actionable_runs(runs, {"BUY"}) == []


def test_build_digest_links_to_signals():
    """ISC-13/14 — digest summarizes actionable runs + links to /signals."""
    uid = uuid.uuid4()
    runs = [_run(uid, "AAPL", rating="BUY"), _run(uid, "TSLA", rating="SELL")]
    d = build_digest(runs, "https://tradix.axiara.ai")
    assert d["count"] == 2
    assert d["link"] == "https://tradix.axiara.ai/signals"
    assert "BUY AAPL" in d["subject"]
    assert "/signals" in d["text"]


# ---- delivery ----

@pytest.mark.asyncio
async def test_deliver_sends_on_actionable(db_session, user):
    """ISC-13/16 — actionable batch → one SENT notification via stub adapter."""
    get_settings.cache_clear()
    runs = [_run(user.id, "AAPL", rating="BUY"), _run(user.id, "MSFT", rating="HOLD")]
    notif = await deliver_for_batch(db_session, user, DATE, runs, get_settings())
    assert notif is not None
    assert notif.status == NotificationStatus.SENT.value
    assert notif.sent_at is not None
    count = (await db_session.execute(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_deliver_records_quiet_day(db_session, user):
    """ISC-19 — quiet day writes a skipped_no_signal row (auditable silence), no send."""
    runs = [_run(user.id, "AAPL", rating="HOLD")]
    notif = await deliver_for_batch(db_session, user, DATE, runs, get_settings())
    assert notif is not None
    assert notif.status == NotificationStatus.SKIPPED_NO_SIGNAL.value
    assert notif.sent_at is None


@pytest.mark.asyncio
async def test_deliver_disabled_writes_no_row(db_session, user):
    """ISC-18 — notify_enabled=False → None + no delivery row."""
    user.notify_enabled = False
    await db_session.commit()
    runs = [_run(user.id, "AAPL", rating="BUY")]
    notif = await deliver_for_batch(db_session, user, DATE, runs, get_settings())
    assert notif is None
    count = (await db_session.execute(
        select(func.count()).select_from(Notification)
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_deliver_channel_none_writes_no_row(db_session, user):
    user.notify_channel = "none"
    await db_session.commit()
    runs = [_run(user.id, "AAPL", rating="BUY")]
    assert await deliver_for_batch(db_session, user, DATE, runs, get_settings()) is None


@pytest.mark.asyncio
async def test_deliver_is_idempotent(db_session, user):
    """ISC-16/22/24 — second delivery for same (user,date,channel) is a no-op."""
    runs = [_run(user.id, "AAPL", rating="BUY")]
    first = await deliver_for_batch(db_session, user, DATE, runs, get_settings())
    second = await deliver_for_batch(db_session, user, DATE, runs, get_settings())
    assert first is not None
    assert second is None
    count = (await db_session.execute(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_send_failure_is_non_fatal(db_session, user, monkeypatch):
    """ISC-17 — adapter.send raising → status FAILED, no exception out."""
    class _Boom:
        name = "email"
        async def send(self, **kw):
            raise RuntimeError("smtp exploded")

    monkeypatch.setattr(notif_mod, "get_adapter", lambda channel, settings: _Boom())
    runs = [_run(user.id, "AAPL", rating="BUY")]
    notif = await deliver_for_batch(db_session, user, DATE, runs, get_settings())
    assert notif is not None
    assert notif.status == NotificationStatus.FAILED.value
    assert "smtp exploded" in (notif.error or "")

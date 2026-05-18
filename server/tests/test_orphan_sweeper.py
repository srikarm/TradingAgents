import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User
from app.workers import tasks as worker_tasks


def _wrapper_factory(session):
    class _W:
        async def __aenter__(_self):
            return session

        async def __aexit__(_self, *exc):
            return False

    def _f():
        return _W()

    return _f


@pytest.mark.asyncio
async def test_orphan_sweeper_marks_stale_running_as_failed(db_session, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-o"))
    now = datetime.now(timezone.utc)
    stale_id = uuid.uuid4()
    fresh_id = uuid.uuid4()
    db_session.add(
        Run(
            id=stale_id, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
            status=RunStatus.RUNNING, results_path="x", created_at=now,
            last_heartbeat_at=now - timedelta(minutes=15),
        )
    )
    db_session.add(
        Run(
            id=fresh_id, user_id=uid, ticker="AAPL", trade_date="2024-05-10",
            status=RunStatus.RUNNING, results_path="x", created_at=now,
            last_heartbeat_at=now - timedelta(seconds=20),
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    stale = (await db_session.execute(select(Run).where(Run.id == stale_id))).scalar_one()
    fresh = (await db_session.execute(select(Run).where(Run.id == fresh_id))).scalar_one()
    assert stale.status is RunStatus.FAILED
    assert stale.error_summary == "worker_lost"
    assert fresh.status is RunStatus.RUNNING


@pytest.mark.asyncio
async def test_orphan_sweeper_ignores_terminal_runs(db_session, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-o2"))
    rid = uuid.uuid4()
    db_session.add(
        Run(
            id=rid, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED, results_path="x",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    run = (await db_session.execute(select(Run).where(Run.id == rid))).scalar_one()
    assert run.status is RunStatus.SUCCEEDED  # untouched


@pytest.mark.asyncio
async def test_orphan_sweeper_marks_stale_queued_as_failed(db_session, monkeypatch):
    """Spec §4: a QUEUED run whose created_at is older than
    queued_threshold_seconds must be marked FAILED with
    error_summary='never_picked_up'. last_heartbeat_at stays NULL."""
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-osq1"))
    now = datetime.now(timezone.utc)
    stale_id = uuid.uuid4()
    db_session.add(
        Run(
            id=stale_id, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
            status=RunStatus.QUEUED, results_path="x",
            created_at=now - timedelta(hours=1),
            # last_heartbeat_at intentionally NULL — QUEUED runs never heartbeat.
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    stale = (await db_session.execute(select(Run).where(Run.id == stale_id))).scalar_one()
    assert stale.status is RunStatus.FAILED
    assert stale.error_summary == "never_picked_up"
    assert stale.completed_at is not None
    assert stale.last_heartbeat_at is None


@pytest.mark.asyncio
async def test_orphan_sweeper_ignores_fresh_queued(db_session, monkeypatch):
    """A QUEUED run whose created_at is within the threshold window must
    stay QUEUED — false-positives would penalize legitimate backlog runs."""
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-osq2"))
    now = datetime.now(timezone.utc)
    fresh_id = uuid.uuid4()
    db_session.add(
        Run(
            id=fresh_id, user_id=uid, ticker="AAPL", trade_date="2024-05-10",
            status=RunStatus.QUEUED, results_path="x",
            created_at=now - timedelta(seconds=60),
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    fresh = (await db_session.execute(select(Run).where(Run.id == fresh_id))).scalar_one()
    assert fresh.status is RunStatus.QUEUED
    assert fresh.error_summary is None
    assert fresh.completed_at is None

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

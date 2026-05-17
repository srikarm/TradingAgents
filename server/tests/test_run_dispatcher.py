import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User
from app.schemas.run import RunCreate
from app.services.run_dispatcher import (
    DuplicateRunningError,
    dispatch_run,
)



class FakePool:
    def __init__(self):
        self.enqueued: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name: str, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return object()


@pytest.mark.asyncio
async def test_dispatch_run_creates_row_and_enqueues(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-d"))
    await db_session.flush()
    pool = FakePool()

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    run = await dispatch_run(
        session=db_session,
        pool=pool,
        user_id=uid,
        dashboard_dir=tmp_path,
        body=body,
    )

    assert run.user_id == uid
    assert run.ticker == "NVDA"
    assert run.status is RunStatus.QUEUED
    assert run.results_path.startswith(str(tmp_path))
    assert len(pool.enqueued) == 1
    name, args, _ = pool.enqueued[0]
    assert name == "run_propagate"
    assert args[0] == str(run.id)


@pytest.mark.asyncio
async def test_dispatch_run_uppercases_ticker(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-u"))
    await db_session.flush()
    body = RunCreate(ticker="nvda", trade_date="2024-05-10")
    run = await dispatch_run(
        session=db_session,
        pool=FakePool(),
        user_id=uid,
        dashboard_dir=tmp_path,
        body=body,
    )
    assert run.ticker == "NVDA"


@pytest.mark.asyncio
async def test_dispatch_run_rejects_duplicate_running(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-x"))
    db_session.add(
        Run(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.RUNNING,
            results_path="x",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    with pytest.raises(DuplicateRunningError):
        await dispatch_run(
            session=db_session,
            pool=FakePool(),
            user_id=uid,
            dashboard_dir=tmp_path,
            body=body,
        )


@pytest.mark.asyncio
async def test_dispatch_run_allows_relaunch_of_completed(db_session, tmp_path):
    """A succeeded or failed run for the same ticker+date doesn't block re-launch."""
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-r"))
    db_session.add(
        Run(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED,
            results_path="x",
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    await db_session.flush()

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    run = await dispatch_run(
        session=db_session,
        pool=FakePool(),
        user_id=uid,
        dashboard_dir=tmp_path,
        body=body,
    )
    assert run.status is RunStatus.QUEUED


@pytest.mark.asyncio
async def test_dispatch_run_marks_failed_when_enqueue_raises(db_session, tmp_path):
    """If pool.enqueue_job raises, the just-committed Run row must be marked FAILED
    so it isn't stuck in QUEUED forever."""
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-enq"))
    await db_session.flush()

    class FailingPool:
        async def enqueue_job(self, *a, **kw):
            raise RuntimeError("redis down")

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    with pytest.raises(RuntimeError, match="redis down"):
        await dispatch_run(
            session=db_session,
            pool=FailingPool(),
            user_id=uid,
            dashboard_dir=tmp_path,
            body=body,
        )

    rows = (await db_session.execute(select(Run))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status is RunStatus.FAILED
    assert rows[0].error_summary == "enqueue_failed"

"""Bridge between POST /runs and the arq queue.

Validates the request, builds a per-user results path via user_root,
inserts a Run row in 'queued' status, and enqueues run_propagate.
Rejects launches that collide with an already-running run for the same
(user, ticker, date).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run, RunStatus
from app.schemas.run import RunCreate
from app.services.user_root import user_run_dir


class _PoolProto(Protocol):
    async def enqueue_job(self, name: str, *args, **kwargs): ...


class DuplicateRunningError(Exception):
    """A run is already queued or running for this (user, ticker, date)."""

    def __init__(self, existing_id: uuid.UUID) -> None:
        self.existing_id = existing_id
        super().__init__(f"duplicate running run: {existing_id}")


async def dispatch_run(
    *,
    session: AsyncSession,
    pool: _PoolProto,
    user_id: uuid.UUID,
    dashboard_dir: Path,
    body: RunCreate,
) -> Run:
    ticker = body.ticker.upper()
    trade_date = body.trade_date

    # Reject collision with active runs.
    blocking = (
        await session.execute(
            select(Run).where(
                Run.user_id == user_id,
                Run.ticker == ticker,
                Run.trade_date == trade_date,
                Run.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
        )
    ).scalar_one_or_none()
    if blocking is not None:
        raise DuplicateRunningError(blocking.id)

    target = user_run_dir(dashboard_dir, str(user_id), ticker, trade_date)
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=trade_date,
        status=RunStatus.QUEUED,
        results_path=str(target),
        created_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()

    await pool.enqueue_job(
        "run_propagate",
        str(run.id),
        _job_id=f"run_{run.id}",
    )
    return run

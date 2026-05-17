"""Concurrent-race regression test for memory_mirror.sync_user.

Without the advisory lock, two simultaneous sync_user() calls for the
same user_id race over the uq_memory_entry_user_ticker_date constraint.
Two failure modes are observable in RED:
  - Both callers return N (one wins the SELECT/INSERT, the other's
    SELECT sees the just-committed rows and takes the UPDATE path);
  - One returns N and the other raises IntegrityError on commit
    (truly concurrent interleaving under cooperative scheduling).

The `sorted([a, b]) == [0, N]` assertion catches both: only the lock
produces a 0 return value. With the lock, the second caller fails
pg_try_advisory_xact_lock, logs a warning, and returns 0.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.memory_entry import MemoryEntry
from app.models.user import User
from app.services.memory_mirror import sync_user

FIXTURE = Path(__file__).parent / "fixtures" / "trading_memory_mixed.md"
N_ENTRIES = 3  # 2 resolved + 1 pending; malformed entry in fixture is skipped


async def _seed(pg_engine, tmp_path) -> uuid.UUID:
    """Insert a User row and write the trading_memory.md fixture to disk.

    Returns the user_id. Uses a one-shot session, then closes it so the
    race coroutines start from a clean slate.
    """
    uid = uuid.uuid4()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=uid, github_id=f"gh-race-{uid}"))
        await s.commit()

    mem_dir = tmp_path / "users" / str(uid) / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "trading_memory.md").write_text(FIXTURE.read_text(encoding="utf-8"))
    return uid


@pytest.mark.pg
@pytest.mark.asyncio
async def test_concurrent_sync_serializes_via_advisory_lock(
    pg_engine, tmp_path, caplog,
):
    uid = await _seed(pg_engine, tmp_path)
    caplog.set_level(logging.WARNING, logger="app.services.memory_mirror")

    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def one_sync() -> int | BaseException:
        async with factory() as s:
            try:
                return await sync_user(s, dashboard_dir=tmp_path, user_id=uid)
            except BaseException as e:  # noqa: BLE001 -- test wants to see ANY failure
                return e

    a, b = await asyncio.gather(one_sync(), one_sync())

    # GREEN expectation: one caller acquires the lock and processes all
    # N entries; the other sees the lock held and returns 0.
    # RED expectation (no lock): one returns N, the other raises
    # IntegrityError on commit due to uq_memory_entry_user_ticker_date.
    assert not isinstance(a, BaseException), f"sync_user raised: {a!r}"
    assert not isinstance(b, BaseException), f"sync_user raised: {b!r}"
    assert sorted([a, b]) == [0, N_ENTRIES], (
        f"expected one sync to win (returned {N_ENTRIES}) and one to skip "
        f"(returned 0); got {a=} {b=}. If both are {N_ENTRIES}, the lock "
        f"is not preventing the race. If one is an exception, the test's "
        f"BaseException guard failed."
    )

    # The skipped caller logged the expected warning.
    skip_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "skipped" in r.message and str(uid) in r.message
    ]
    assert len(skip_warnings) == 1, (
        f"expected exactly one 'skipped' WARNING mentioning user_id={uid}, "
        f"got: {[r.message for r in caplog.records]}"
    )

    # No duplicate rows — uq_memory_entry_user_ticker_date upheld.
    async with factory() as s:
        rows = (
            await s.execute(select(MemoryEntry).where(MemoryEntry.user_id == uid))
        ).scalars().all()
    assert len(rows) == N_ENTRIES, (
        f"expected exactly {N_ENTRIES} rows for user {uid}, got {len(rows)} "
        f"(duplicates indicate the lock failed)"
    )

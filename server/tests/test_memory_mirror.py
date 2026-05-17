import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.models.user import User
from app.services.memory_mirror import sync_user

FIXTURE = Path(__file__).parent / "fixtures" / "trading_memory_mixed.md"


@pytest.mark.asyncio
async def test_sync_user_inserts_resolved_and_pending(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-mm"))
    await db_session.flush()

    mem_dir = tmp_path / "users" / str(uid) / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "trading_memory.md").write_text(FIXTURE.read_text(encoding="utf-8"))

    count = await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)
    assert count == 3  # 2 resolved + 1 pending; malformed skipped

    rows = (
        await db_session.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == uid).order_by(MemoryEntry.trade_date)
        )
    ).scalars().all()
    by_ticker = {r.ticker: r for r in rows}

    assert by_ticker["NVDA"].status is MemoryEntryStatus.RESOLVED
    assert by_ticker["NVDA"].raw_return == pytest.approx(0.023)
    assert by_ticker["NVDA"].alpha_return == pytest.approx(0.011)
    assert by_ticker["NVDA"].holding_days == 7

    assert by_ticker["TSLA"].raw_return == pytest.approx(-0.015)

    assert by_ticker["AAPL"].status is MemoryEntryStatus.PENDING
    assert by_ticker["AAPL"].raw_return is None


@pytest.mark.asyncio
async def test_sync_user_is_idempotent(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-mm2"))
    await db_session.flush()

    mem_dir = tmp_path / "users" / str(uid) / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "trading_memory.md").write_text(FIXTURE.read_text(encoding="utf-8"))

    await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)
    await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)

    count = (
        await db_session.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == uid)
        )
    ).scalars().all()
    assert len(count) == 3  # no duplicates


@pytest.mark.asyncio
async def test_sync_user_updates_pending_when_resolved_on_disk(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-mm3"))
    await db_session.flush()

    pending_md = (
        "[2024-05-11 | AAPL | Hold | pending]\n\nDECISION:\nfoo\n\n<!-- ENTRY_END -->\n\n"
    )
    resolved_md = (
        "[2024-05-11 | AAPL | Hold | +0.5% | +0.1% | 3d]\n\nDECISION:\nfoo\n\n"
        "REFLECTION:\nmoved\n\n<!-- ENTRY_END -->\n\n"
    )

    mem_dir = tmp_path / "users" / str(uid) / "memory"
    mem_dir.mkdir(parents=True)
    log = mem_dir / "trading_memory.md"
    log.write_text(pending_md)

    await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)
    row = (await db_session.execute(select(MemoryEntry))).scalar_one()
    assert row.status is MemoryEntryStatus.PENDING
    assert row.raw_return is None

    log.write_text(resolved_md)
    await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)
    db_session.expire_all()
    row = (await db_session.execute(select(MemoryEntry))).scalar_one()
    assert row.status is MemoryEntryStatus.RESOLVED
    assert row.raw_return == pytest.approx(0.005)


@pytest.mark.asyncio
async def test_sync_user_no_file_is_noop(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-mm4"))
    await db_session.flush()
    count = await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)
    assert count == 0

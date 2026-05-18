"""Regression guard for v3+ followup #5: MemoryEntry.updated_at must
auto-refresh on every ORM UPDATE so callers cannot leave the timestamp
stale by forgetting to set it. See dashboard wave 3 deferred items."""

import uuid
from datetime import datetime

import pytest

from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_updated_at_auto_refreshes_on_orm_update(db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-updated-at"))
    past = datetime(2000, 1, 1)

    entry = MemoryEntry(
        id=uuid.uuid4(),
        user_id=uid,
        ticker="NVDA",
        trade_date="2024-01-01",
        rating="Buy",
        status=MemoryEntryStatus.PENDING,
        created_at=past,
        updated_at=past,
    )
    db_session.add(entry)
    await db_session.commit()

    # ORM UPDATE that does NOT touch updated_at — onupdate=func.now()
    # must emit a fresh timestamp so the column never lies.
    entry.rating = "Hold"
    await db_session.commit()
    await db_session.refresh(entry)

    assert entry.updated_at > past, (
        f"updated_at did not auto-refresh on ORM update — "
        f"still {entry.updated_at!r}, expected > {past!r}. "
        f"Add onupdate=func.now() to MemoryEntry.updated_at."
    )

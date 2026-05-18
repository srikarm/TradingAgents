import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.models.run import Run, RunStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_user_insert_and_query(db_session):
    u = User(id=uuid.uuid4(), github_id="123", email="a@example.com")
    db_session.add(u)
    await db_session.flush()
    rows = (await db_session.execute(select(User))).scalars().all()
    assert len(rows) == 1
    assert rows[0].github_id == "123"


@pytest.mark.asyncio
async def test_run_insert_and_query(db_session):
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, github_id="42", email="b@example.com"))
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker="NVDA",
        trade_date="2024-05-10",
        status=RunStatus.SUCCEEDED,
        results_path="users/" + str(user_id) + "/NVDA/2024-05-10",
        final_rating="Buy",
        created_at=datetime.utcnow(),
    )
    db_session.add(run)
    await db_session.flush()
    found = (await db_session.execute(select(Run))).scalar_one()
    assert found.ticker == "NVDA"
    assert found.status is RunStatus.SUCCEEDED


# ---- MemoryEntry tests ----


@pytest.mark.asyncio
async def test_memory_entry_round_trips_pending(db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-me1"))
    entry = MemoryEntry(
        id=uuid.uuid4(),
        user_id=uid,
        ticker="NVDA",
        trade_date="2024-05-10",
        rating="Buy",
        status=MemoryEntryStatus.PENDING,
        raw_return=None,
        alpha_return=None,
        holding_days=None,
        decision_text="rationale",
        reflection_text=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(entry)
    await db_session.flush()
    found = (await db_session.execute(select(MemoryEntry))).scalar_one()
    assert found.status is MemoryEntryStatus.PENDING
    assert found.raw_return is None


@pytest.mark.asyncio
async def test_memory_entry_round_trips_resolved(db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-me2"))
    entry = MemoryEntry(
        id=uuid.uuid4(),
        user_id=uid,
        ticker="NVDA",
        trade_date="2024-05-10",
        rating="Buy",
        status=MemoryEntryStatus.RESOLVED,
        raw_return=0.023,
        alpha_return=0.011,
        holding_days=7,
        decision_text="rationale",
        reflection_text="worked because earnings beat",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(entry)
    await db_session.flush()
    found = (await db_session.execute(select(MemoryEntry))).scalar_one()
    assert found.status is MemoryEntryStatus.RESOLVED
    assert found.raw_return == pytest.approx(0.023)
    assert found.holding_days == 7


@pytest.mark.asyncio
async def test_resolved_without_raw_return_rejected(db_session):
    """ck_memory_entry_resolved_has_raw_return enforces the invariant:
    status=RESOLVED ⟹ raw_return IS NOT NULL.
    """
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-ck"))
    await db_session.flush()

    db_session.add(
        MemoryEntry(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-09",
            rating="Buy",
            status=MemoryEntryStatus.RESOLVED,
            raw_return=None,
            alpha_return=None,
            holding_days=None,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()

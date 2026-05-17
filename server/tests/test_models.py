import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

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

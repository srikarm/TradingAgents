# server/tests/test_runs_active_count.py
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.run import Run, RunStatus
from app.models.user import User
from tests.conftest import make_jwt

GITHUB_ID = "test-user-active-count"


@pytest.fixture
def client(db_session):
    # Clear LRU cache so stale NEXTAUTH_SECRET from prior tests doesn't bleed in.
    get_settings.cache_clear()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


@pytest.fixture
async def authed_user(db_session) -> User:
    u = User(id=uuid.uuid4(), github_id=GITHUB_ID)
    db_session.add(u)
    await db_session.flush()
    return u


def _make_run(user_id: uuid.UUID, status: RunStatus) -> Run:
    return Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker="TEST.JK",
        trade_date="2026-05-21",
        status=status,
        results_path="",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_zero_count_when_no_runs(client):
    """User with no runs at all -> count = 0."""
    async with client as c:
        res = await c.get(
            "/runs/active/count",
            headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
        )
    assert res.status_code == 200
    assert res.json() == {"count": 0}


@pytest.mark.asyncio
async def test_zero_count_when_only_terminal_runs(client, db_session, authed_user):
    """User has SUCCEEDED + FAILED runs but no active ones -> count = 0."""
    db_session.add(_make_run(authed_user.id, RunStatus.SUCCEEDED))
    db_session.add(_make_run(authed_user.id, RunStatus.FAILED))
    await db_session.flush()

    async with client as c:
        res = await c.get(
            "/runs/active/count",
            headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
        )
    assert res.status_code == 200
    assert res.json() == {"count": 0}


@pytest.mark.asyncio
async def test_counts_queued_and_running(client, db_session, authed_user):
    """Two QUEUED + one RUNNING -> count = 3. SUCCEEDED is ignored."""
    db_session.add(_make_run(authed_user.id, RunStatus.QUEUED))
    db_session.add(_make_run(authed_user.id, RunStatus.QUEUED))
    db_session.add(_make_run(authed_user.id, RunStatus.RUNNING))
    db_session.add(_make_run(authed_user.id, RunStatus.SUCCEEDED))
    await db_session.flush()

    async with client as c:
        res = await c.get(
            "/runs/active/count",
            headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
        )
    assert res.status_code == 200
    assert res.json() == {"count": 3}


@pytest.mark.asyncio
async def test_scoped_to_current_user(client, db_session, authed_user):
    """Other user's in-progress runs do NOT count toward current user's total."""
    other = User(id=uuid.uuid4(), github_id="other-user-999")
    db_session.add(other)
    db_session.add(_make_run(other.id, RunStatus.RUNNING))
    db_session.add(_make_run(other.id, RunStatus.RUNNING))

    db_session.add(_make_run(authed_user.id, RunStatus.RUNNING))
    await db_session.flush()

    async with client as c:
        res = await c.get(
            "/runs/active/count",
            headers={"Authorization": f"Bearer {make_jwt(GITHUB_ID)}"},
        )
    assert res.status_code == 200
    assert res.json() == {"count": 1}

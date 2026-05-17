import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.run import Run, RunStatus
from app.models.user import User
from tests.conftest import make_jwt


@pytest.fixture
def client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


def _seed_run(db, *, user_id, status=RunStatus.RUNNING, results_path):
    rid = uuid.uuid4()
    db.add(
        Run(
            id=rid, user_id=user_id, ticker="NVDA", trade_date="2024-05-10",
            status=status, results_path=str(results_path),
            created_at=datetime.now(timezone.utc),
        )
    )
    return rid


@pytest.mark.asyncio
async def test_tail_returns_log_bytes(client, db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-t"))
    rdir = tmp_path / "NVDA" / "2024-05-10"
    rdir.mkdir(parents=True)
    (rdir / "message_tool.log").write_text("hello\n")
    rid = _seed_run(db_session, user_id=uid, results_path=rdir)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{rid}/tail?since=0",
            headers={"Authorization": f"Bearer {make_jwt('gh-t')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "hello\n"
    assert body["next_offset"] == len(b"hello\n")
    assert body["status"] == "running"


@pytest.mark.asyncio
async def test_tail_returns_empty_when_log_missing(client, db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-tm"))
    rdir = tmp_path / "NVDA" / "2024-05-10"
    rdir.mkdir(parents=True)
    rid = _seed_run(db_session, user_id=uid, status=RunStatus.QUEUED, results_path=rdir)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{rid}/tail?since=0",
            headers={"Authorization": f"Bearer {make_jwt('gh-tm')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == ""
    assert body["next_offset"] == 0
    assert body["status"] == "queued"


@pytest.mark.asyncio
async def test_tail_404_for_other_users_run(client, db_session, tmp_path):
    me, other = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me, github_id="gh-me"))
    db_session.add(User(id=other, github_id="gh-other"))
    rdir = tmp_path / "AAPL" / "2024-05-10"
    rdir.mkdir(parents=True)
    rid = _seed_run(db_session, user_id=other, results_path=rdir)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{rid}/tail?since=0",
            headers={"Authorization": f"Bearer {make_jwt('gh-me')}"},
        )
    assert r.status_code == 404

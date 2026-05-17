import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.user import User
from tests.conftest import make_jwt


class FakePool:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return object()

    async def close(self): pass


@pytest.fixture
def fake_pool():
    return FakePool()


@pytest.fixture
def client(db_session, fake_pool, monkeypatch):
    async def _override_db():
        yield db_session

    async def _override_pool():
        yield fake_pool

    from app.routers.runs import get_pool
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_pool] = _override_pool
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_runs_creates_and_enqueues(client, db_session, fake_pool, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    db_session.add(User(id=uuid.uuid4(), github_id="gh-p"))
    await db_session.flush()

    async with client as c:
        r = await c.post(
            "/runs",
            json={"ticker": "NVDA", "trade_date": "2024-05-10"},
            headers={"Authorization": f"Bearer {make_jwt('gh-p')}"},
        )
    assert r.status_code == 202
    assert "run_id" in r.json()
    assert len(fake_pool.enqueued) == 1


@pytest.mark.asyncio
async def test_post_runs_409_on_duplicate_running(client, db_session, fake_pool, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from app.models.run import Run, RunStatus

    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-q"))
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

    async with client as c:
        r = await c.post(
            "/runs",
            json={"ticker": "NVDA", "trade_date": "2024-05-10"},
            headers={"Authorization": f"Bearer {make_jwt('gh-q')}"},
        )
    assert r.status_code == 409
    assert "existing_run_id" in r.json()["detail"]


@pytest.mark.asyncio
async def test_post_runs_422_on_bad_ticker(client, db_session, fake_pool):
    async with client as c:
        r = await c.post(
            "/runs",
            json={"ticker": "", "trade_date": "2024-05-10"},
            headers={"Authorization": f"Bearer {make_jwt('gh-z')}"},
        )
    assert r.status_code == 422

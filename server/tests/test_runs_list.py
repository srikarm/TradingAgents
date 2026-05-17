import uuid
from datetime import datetime

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


def _add_run(session, *, user_id, ticker, date, status=RunStatus.SUCCEEDED, rating="Buy"):
    r = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=date,
        status=status,
        final_rating=rating,
        results_path=f"users/{user_id}/{ticker}/{date}",
        created_at=datetime.utcnow(),
    )
    session.add(r)
    return r


@pytest.mark.asyncio
async def test_runs_list_filters_by_authenticated_user(client, db_session):
    me_id, other_id = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me_id, github_id="gh-me"))
    db_session.add(User(id=other_id, github_id="gh-other"))
    _add_run(db_session, user_id=me_id, ticker="NVDA", date="2024-05-10")
    _add_run(db_session, user_id=me_id, ticker="AAPL", date="2024-05-09")
    _add_run(db_session, user_id=other_id, ticker="TSLA", date="2024-05-08")
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/runs",
            headers={"Authorization": f"Bearer {make_jwt('gh-me')}"},
        )
    assert r.status_code == 200
    items = r.json()["items"]
    assert {it["ticker"] for it in items} == {"NVDA", "AAPL"}
    # newest first
    assert items[0]["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_runs_list_supports_ticker_filter(client, db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-f"))
    _add_run(db_session, user_id=uid, ticker="NVDA", date="2024-05-10")
    _add_run(db_session, user_id=uid, ticker="AAPL", date="2024-05-09")
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/runs?ticker=NVDA",
            headers={"Authorization": f"Bearer {make_jwt('gh-f')}"},
        )
    assert r.status_code == 200
    items = r.json()["items"]
    assert {it["ticker"] for it in items} == {"NVDA"}


@pytest.mark.asyncio
async def test_runs_list_requires_auth(client):
    async with client as c:
        r = await c.get("/runs")
    assert r.status_code == 401

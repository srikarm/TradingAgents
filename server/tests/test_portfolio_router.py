import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.models.user import User
from tests.conftest import make_jwt


@pytest.fixture
def client(db_session, monkeypatch):
    # Disable the per-request mirror so these tests focus on read math
    from app.routers import portfolio as portfolio_router

    async def noop(*a, **kw):
        return 0

    monkeypatch.setattr(portfolio_router, "_sync_user", noop)

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


def _add_entry(session, *, user_id, ticker, trade_date, rating,
               raw=None, status=MemoryEntryStatus.RESOLVED):
    e = MemoryEntry(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=trade_date,
        rating=rating,
        status=status,
        raw_return=raw,
        alpha_return=None,
        holding_days=None,
        decision_text=None,
        reflection_text=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(e)


@pytest.mark.asyncio
async def test_summary_aggregates_only_current_user(client, db_session):
    me, other = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me, github_id="gh-pm"))
    db_session.add(User(id=other, github_id="gh-po"))
    _add_entry(db_session, user_id=me, ticker="NVDA", trade_date="2024-05-09",
               rating="Buy", raw=0.02)
    _add_entry(db_session, user_id=me, ticker="AAPL", trade_date="2024-05-10",
               rating="Sell", raw=0.01)  # -1 * 0.01 = -0.01
    _add_entry(db_session, user_id=other, ticker="TSLA", trade_date="2024-05-10",
               rating="Buy", raw=0.99)  # MUST NOT leak
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/portfolio/summary",
            headers={"Authorization": f"Bearer {make_jwt('gh-pm')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["trade_count"] == 2
    assert body["cumulative_return"] == pytest.approx(0.01)
    assert body["win_rate"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_summary_requires_auth(client):
    async with client as c:
        r = await c.get("/portfolio/summary")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_summary_empty_returns_zeros(client, db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-pe"))
    await db_session.flush()
    async with client as c:
        r = await c.get(
            "/portfolio/summary",
            headers={"Authorization": f"Bearer {make_jwt('gh-pe')}"},
        )
    assert r.status_code == 200
    assert r.json() == {
        "trade_count": 0,
        "win_rate": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "cumulative_return": 0.0,
    }


@pytest.mark.asyncio
async def test_curve_returns_points_in_order(client, db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-pc"))
    _add_entry(db_session, user_id=uid, ticker="NVDA", trade_date="2024-05-09",
               rating="Buy", raw=0.02)
    _add_entry(db_session, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
               rating="Sell", raw=0.01)  # -0.01
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/portfolio/curve",
            headers={"Authorization": f"Bearer {make_jwt('gh-pc')}"},
        )
    assert r.status_code == 200
    points = r.json()["points"]
    assert [p["trade_date"] for p in points] == ["2024-05-09", "2024-05-10"]
    assert points[0]["cumulative_pnl"] == pytest.approx(0.02)
    assert points[1]["cumulative_pnl"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_curve_ignores_pending_entries(client, db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-pp"))
    _add_entry(db_session, user_id=uid, ticker="NVDA", trade_date="2024-05-09",
               rating="Buy", raw=0.02)
    _add_entry(db_session, user_id=uid, ticker="AAPL", trade_date="2024-05-10",
               rating="Hold", raw=None, status=MemoryEntryStatus.PENDING)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/portfolio/curve",
            headers={"Authorization": f"Bearer {make_jwt('gh-pp')}"},
        )
    assert r.status_code == 200
    assert len(r.json()["points"]) == 1

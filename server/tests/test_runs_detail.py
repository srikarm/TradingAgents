import uuid
from datetime import datetime
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


def _seed_run_on_disk(root: Path, user_id, ticker, date) -> Path:
    base = root / "users" / str(user_id) / ticker / date / "reports"
    (base / "1_analysts").mkdir(parents=True)
    (base / "2_research").mkdir(parents=True)
    (base / "3_trading").mkdir(parents=True)
    (base / "1_analysts" / "market.md").write_text("# market report")
    (base / "2_research" / "manager.md").write_text("# research mgr")
    (base / "3_trading" / "trader.md").write_text("# trader plan")
    (base / "final_trade_decision.md").write_text("# final")
    return base.parent.parent.parent.parent


@pytest.mark.asyncio
async def test_run_detail_returns_markdown_sections(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-d"))
    _seed_run_on_disk(tmp_path, uid, "NVDA", "2024-05-10")
    run_id = uuid.uuid4()
    db_session.add(
        Run(
            id=run_id,
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED,
            final_rating="Buy",
            results_path=str(tmp_path / "users" / str(uid) / "NVDA" / "2024-05-10"),
            created_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{run_id}",
            headers={"Authorization": f"Bearer {make_jwt('gh-d')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["report_sections"]["market"].startswith("# market")
    assert body["report_sections"]["final"].startswith("# final")
    assert body["report_sections"]["sentiment"] is None


@pytest.mark.asyncio
async def test_run_detail_404_for_other_users_run(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    me, other = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me, github_id="gh-me"))
    db_session.add(User(id=other, github_id="gh-other"))
    other_run = uuid.uuid4()
    db_session.add(
        Run(
            id=other_run,
            user_id=other,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED,
            results_path="x",
            created_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{other_run}",
            headers={"Authorization": f"Bearer {make_jwt('gh-me')}"},
        )
    # 404, NOT 403 — avoid existence oracle.
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_run_detail_422_for_non_uuid(client):
    async with client as c:
        r = await c.get(
            "/runs/not-a-uuid",
            headers={"Authorization": f"Bearer {make_jwt('gh-x')}"},
        )
    assert r.status_code == 422

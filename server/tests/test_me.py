import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from tests.conftest import make_jwt


@pytest.fixture
def client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_me_returns_user_payload(client):
    token = make_jwt("gh-77", email="x@example.com")
    async with client as c:
        r = await c.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["github_id"] == "gh-77"
    assert body["email"] == "x@example.com"
    assert "id" in body and "created_at" in body

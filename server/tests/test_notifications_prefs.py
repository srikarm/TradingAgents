"""Wave 5.4 — GET/PATCH /me/notifications prefs endpoint."""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.user import User
from tests.conftest import make_jwt

GITHUB_ID = "test-user-notify"
EMAIL = "notify@example.com"


@pytest_asyncio.fixture
async def authed_user(db_session) -> User:
    u = User(id=uuid.uuid4(), github_id=GITHUB_ID, email=EMAIL)
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def client(db_session, authed_user):
    get_settings.cache_clear()
    await db_session.commit()
    request_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def _override_db():
        async with request_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    token = make_jwt(GITHUB_ID, email=EMAIL)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_defaults(client):
    """ISC-8 — fresh user: disabled, channel none, default threshold."""
    res = await client.get("/me/notifications")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "enabled": False,
        "channel": "none",
        "threshold": "BUY,SELL",
        "deliverable": False,
    }


@pytest.mark.asyncio
async def test_enable_email_with_address(client):
    """ISC-9 — enabling email with an address on record → 200 + deliverable."""
    res = await client.patch("/me/notifications", json={"enabled": True, "channel": "email"})
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["channel"] == "email"
    assert body["deliverable"] is True


@pytest.mark.asyncio
async def test_enable_email_without_address_422(db_session):
    """ISC-9 — a user with no email cannot enable the email channel."""
    gh = "no-email-user"
    u = User(id=uuid.uuid4(), github_id=gh, email=None)
    db_session.add(u)
    await db_session.commit()
    request_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def _override_db():
        async with request_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    token = make_jwt(gh, email=None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        res = await c.patch("/me/notifications", json={"enabled": True, "channel": "email"})
    app.dependency_overrides.clear()
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invalid_channel_422(client):
    res = await client.patch("/me/notifications", json={"enabled": True, "channel": "carrier-pigeon"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_custom_threshold_persists(client):
    res = await client.patch("/me/notifications", json={
        "enabled": True, "channel": "email", "threshold": "BUY",
    })
    assert res.status_code == 200
    assert res.json()["threshold"] == "BUY"


@pytest.mark.asyncio
async def test_omitted_fields_fall_back_to_stored(client):
    """ISC-10 — re-enable with just {enabled: true} keeps the prior channel."""
    await client.patch("/me/notifications", json={"enabled": True, "channel": "email", "threshold": "SELL"})
    await client.patch("/me/notifications", json={"enabled": False})
    res = await client.patch("/me/notifications", json={"enabled": True})
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["channel"] == "email"   # preserved
    assert body["threshold"] == "SELL"  # preserved

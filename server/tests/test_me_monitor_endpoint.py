# server/tests/test_me_monitor_endpoint.py
"""Tests for PATCH /me/monitor + extended GET /me."""
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

GITHUB_ID = "test-user-me-monitor"


@pytest_asyncio.fixture
async def authed_user(db_session) -> User:
    """Pre-create the user that the bearer JWT will resolve to."""
    u = User(id=uuid.uuid4(), github_id=GITHUB_ID)
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def async_client_authed(db_session, authed_user):
    """An httpx AsyncClient with Authorization header pre-set.

    Mirrors the Wave 5.1 watchlist fixture pattern: a NEW per-request session
    bound to the same engine as db_session.
    """
    get_settings.cache_clear()
    await db_session.commit()

    request_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def _override_db():
        async with request_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    token = make_jwt(GITHUB_ID)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_me_includes_monitor_fields(async_client_authed):
    """GET /me returns the 3 new monitor fields (all null/false for new users)."""
    res = await async_client_authed.get("/me")
    assert res.status_code == 200
    body = res.json()
    assert body["monitor_enabled"] is False
    assert body["briefing_time_local"] is None
    assert body["briefing_tz"] is None


@pytest.mark.asyncio
async def test_patch_monitor_enable_valid(async_client_authed):
    """PATCH /me/monitor with valid enable payload → 200 + persisted + next_briefing_at."""
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True,
        "briefing_time_local": "07:00",
        "briefing_tz": "Asia/Jakarta",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["briefing_time_local"] == "07:00"
    assert body["briefing_tz"] == "Asia/Jakarta"
    assert "next_briefing_at" in body


@pytest.mark.asyncio
async def test_patch_monitor_enable_missing_time_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_tz": "Asia/Jakarta",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_enable_missing_tz_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "07:00",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_invalid_tz_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "07:00", "briefing_tz": "Not/A/Zone",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_invalid_time_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "25:00", "briefing_tz": "Asia/Jakarta",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_disable_preserves_config(async_client_authed):
    """Disable preserves time+tz so re-enable restores prior config."""
    await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "07:00", "briefing_tz": "Asia/Jakarta",
    })
    res = await async_client_authed.patch("/me/monitor", json={"enabled": False})
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    # Time + tz should still be there (preserved for re-enable):
    assert body["briefing_time_local"] == "07:00"
    assert body["briefing_tz"] == "Asia/Jakarta"

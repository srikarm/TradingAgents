import uuid

import pytest
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import get_current_user
from app.models.user import User
from tests.conftest import make_expired_jwt, make_jwt


@pytest.fixture
def auth_app(db_session):
    app = FastAPI()

    async def _override_db():
        yield db_session

    from app.db import get_db
    app.dependency_overrides[get_db] = _override_db

    @app.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)):
        return {"id": str(user.id), "github_id": user.github_id}

    return app


async def _call(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/whoami", headers=headers)


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(auth_app):
    r = await _call(auth_app, {})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_jwt_upserts_user(auth_app, db_session):
    token = make_jwt("gh-100")
    r = await _call(auth_app, {"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["github_id"] == "gh-100"
    rows = (await db_session.execute(select(User))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_repeat_login_does_not_duplicate_user(auth_app, db_session):
    token = make_jwt("gh-200")
    await _call(auth_app, {"Authorization": f"Bearer {token}"})
    await _call(auth_app, {"Authorization": f"Bearer {token}"})
    rows = (await db_session.execute(select(User))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(auth_app):
    r = await _call(auth_app, {"Authorization": f"Bearer {make_expired_jwt('gh-300')}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bad_signature_returns_401(auth_app):
    token = make_jwt("gh-400")
    tampered = token[:-4] + "xxxx"
    r = await _call(auth_app, {"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401

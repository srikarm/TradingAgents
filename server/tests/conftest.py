import os

os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-do-not-use-in-prod-xxxxxxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DASHBOARD_DATA_DIR", "/tmp/trading-test")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
# Import models so their tables are registered on Base.metadata
from app.models import user as _user  # noqa: F401
from app.models import run as _run  # noqa: F401
from app.models import memory_entry as _memory_entry  # noqa: F401


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


import datetime as _dt
import time

import jwt


def make_jwt(github_id: str, email: str | None = "a@example.com", *, exp_in: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": github_id, "email": email, "iat": now, "exp": now + exp_in},
        os.environ["NEXTAUTH_SECRET"],
        algorithm="HS256",
    )


def make_expired_jwt(github_id: str) -> str:
    return make_jwt(github_id, exp_in=-10)

"""Postgres-backed fixtures for tests marked @pytest.mark.pg.

Boots a single throwaway Postgres container per pytest session (via
testcontainers-python). Exposes an async engine so individual tests can
build their own session factories — the concurrent test in
test_memory_mirror_concurrent_pg.py needs two separate sessions because
the xact-variant advisory lock is transaction-scoped, and one session
provides only one active transaction. Two coroutines sharing a single
session would share one transaction and never contend with each other.

Default `pytest` deselects the `pg` marker; run with `pytest -m pg` to
include these tests. Requires Docker.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

# Import all models so their tables are registered on Base.metadata.
from app.models import memory_entry as _memory_entry  # noqa: F401
from app.models import run as _run  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.models.base import Base


@pytest.fixture(scope="session")
def pg_container():
    """Boot one Postgres 16 container per pytest session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture
async def pg_engine(pg_container):
    """Yield an async SQLAlchemy engine with fresh schema per test."""
    sync_url = pg_container.get_connection_url()
    # testcontainers returns postgresql+psycopg2://; we use asyncpg.
    async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if async_url == sync_url:  # fallback for older testcontainers that return plain postgresql://
        async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # pool_size must be >= the number of concurrent sync_user calls a single
    # test makes (currently 2 for the race test) so both coroutines can have
    # their lock SELECT in flight at the same time. Otherwise B might block
    # on connection acquisition until A commits, hiding the race.
    engine = create_async_engine(async_url, pool_size=4, max_overflow=2)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        finally:
            await engine.dispose()

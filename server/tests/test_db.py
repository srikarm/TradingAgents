import pytest
from sqlalchemy import text

from app.db import get_engine, get_session_factory


@pytest.mark.asyncio
async def test_engine_round_trip():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_session_factory_yields_async_session():
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(text("SELECT 2"))
        assert result.scalar() == 2

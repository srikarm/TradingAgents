"""Migration backfill smoke test for b1c2d3e4f5a6_memory_entry_resolved_check.

We don't run the full alembic environment here (it pulls in app config and is
overkill for verifying a SQL UPDATE). Instead we hand-build the
pre-this-migration shape of memory_entries, seed a violating row, then call
the migration's upgrade() and assert the backfill + constraint take effect.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


def _import_migration():
    """Load the migration module by file path (it isn't on sys.path)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "alembic" / "versions" \
        / "b1c2d3e4f5a6_memory_entry_resolved_check.py"
    spec = importlib.util.spec_from_file_location("_mig_b1c2", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def pre_migration_engine():
    """Build the pre-this-migration shape of memory_entries (no CHECK)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE memory_entries ("
            "id TEXT PRIMARY KEY,"
            "status TEXT NOT NULL,"
            "raw_return FLOAT"
            ")"
        ))
        await conn.execute(text(
            "INSERT INTO memory_entries (id, status, raw_return) "
            "VALUES (:id, 'RESOLVED', NULL)"
        ), {"id": str(uuid.uuid4())})
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_demotes_bad_rows_and_adds_constraint(pre_migration_engine):
    mig = _import_migration()
    engine = pre_migration_engine

    def _run_upgrade(sync_conn):
        ctx = MigrationContext.configure(sync_conn)
        with Operations.context(ctx):
            mig.upgrade()

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    # 1. The previously-bad row is now PENDING.
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT status, raw_return FROM memory_entries"
        ))).all()
    assert len(rows) == 1
    assert rows[0][0] == "PENDING"
    assert rows[0][1] is None

    # 2. The constraint now rejects new violators.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO memory_entries (id, status, raw_return) "
                "VALUES (:id, 'RESOLVED', NULL)"
            ), {"id": str(uuid.uuid4())})

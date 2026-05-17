# `memory_mirror` Advisory Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Postgres `pg_try_advisory_xact_lock` around the body of `memory_mirror.sync_user()` so concurrent callers serialize cleanly — the second caller logs a warning and returns 0 instead of racing into an `IntegrityError`. Implements spec §6 (deferred from PR #3).

**Architecture:** Lock acquisition lives inside `sync_user` at the top of the function. Two-key advisory lock: `(NAMESPACE=0x4D4D5252, blake2b(user_id.bytes, 4))`. Transaction-scoped (auto-releases on COMMIT/ROLLBACK, no leak path). Dialect-gated so SQLite tests no-op the acquisition. One new Postgres-backed concurrent test verifies real serialization; the existing SQLite test suite is preserved unchanged. Call sites (worker post-run + 3 portfolio routers via `_sync_user_safe`) get **zero diff** — they all already tolerate `processed == 0`.

**Tech Stack:** Python 3.10+, SQLAlchemy 2.0 async, asyncpg, pytest-asyncio, testcontainers-python (new dev dep), Postgres 16.

**Spec reference:** `docs/superpowers/specs/2026-05-18-memory-mirror-advisory-lock-design.md`

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `server/pyproject.toml` | MODIFY | Add `testcontainers[postgres]` dev dep; register `pg` pytest marker. |
| `server/tests/conftest_pg.py` | CREATE | Session-scoped Postgres testcontainer + `pg_engine` async fixture. Opt-in via `pytest -m pg`. |
| `server/tests/test_memory_mirror_concurrent_pg.py` | CREATE | One concurrent-race test: two `sync_user` coroutines under `asyncio.gather` → asserts `[0, N]` results, warning logged, no duplicate rows. |
| `server/app/services/memory_mirror.py` | MODIFY | Add `NAMESPACE`, `_user_key`, `_try_acquire`. Wrap `sync_user` body with try-acquire and skip-with-warning return. |

No other files change. No call-site edits. No Alembic migration. No frontend.

---

## Task 1: Add `testcontainers[postgres]` dev dep + register `pg` pytest marker

**Files:**
- Modify: `server/pyproject.toml`

- [ ] **Step 1: Read the current dev dep group**

Open `server/pyproject.toml`. The relevant region:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "anyio>=4.6",
    "ruff>=0.7",
]
```

And:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra"
```

- [ ] **Step 2: Add the testcontainers dep + marker registration + default deselect**

Replace the `dev` group above with:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "anyio>=4.6",
    "ruff>=0.7",
    "testcontainers[postgres]>=4.8",
]
```

And replace the `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra -m 'not pg'"
markers = [
    "pg: requires a real Postgres backend (uses testcontainers + Docker); excluded by default. Run with `pytest -m pg` or `pytest -m 'pg or not pg'` to include.",
]
```

The `-m 'not pg'` in `addopts` ensures `pytest` (no args) skips pg tests on machines without Docker. To run them: `pytest -m pg` or `pytest -m 'pg or not pg'`.

- [ ] **Step 3: Sync deps and verify the marker is registered**

Run:

```bash
cd server && uv sync
```

Expected: `testcontainers` resolves and installs. No errors.

Then:

```bash
cd server && uv run pytest --markers | grep -A1 "^@pytest.mark.pg"
```

Expected output (one match):

```
@pytest.mark.pg: requires a real Postgres backend (uses testcontainers + Docker); excluded by default. Run with `pytest -m pg` or `pytest -m 'pg or not pg'` to include.
```

- [ ] **Step 4: Verify default `pytest` still passes (full SQLite suite, pg tests deselected)**

Run:

```bash
cd server && uv run pytest -q
```

Expected: all 133+ existing tests pass; bottom shows `... passed, ... deselected` (deselected count is 0 because no pg tests exist yet, but the `-m 'not pg'` filter is now active for future runs).

- [ ] **Step 5: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/pyproject.toml server/uv.lock
git commit -m "$(cat <<'EOF'
chore(server): add testcontainers dev dep + pg pytest marker

Prep for memory_mirror advisory-lock concurrent test. Marker is
deselected by default so contributors without Docker run pytest
as today.
EOF
)"
```

---

## Task 2: Create Postgres testcontainer fixture

**Files:**
- Create: `server/tests/conftest_pg.py`

- [ ] **Step 1: Write the fixture file**

Create `server/tests/conftest_pg.py` with this exact content:

```python
"""Postgres-backed fixtures for tests marked @pytest.mark.pg.

Boots a single throwaway Postgres container per pytest session (via
testcontainers-python). Exposes an async engine so individual tests can
build their own session factories — the concurrent test in
test_memory_mirror_concurrent_pg.py needs two separate sessions on two
separate connections (advisory locks are connection-scoped; a single
session can't deadlock against itself).

Default `pytest` deselects the `pg` marker; run with `pytest -m pg` to
include these tests. Requires Docker.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from app.models.base import Base

# Import all models so their tables are registered on Base.metadata.
from app.models import memory_entry as _me  # noqa: F401
from app.models import run as _run  # noqa: F401
from app.models import user as _user  # noqa: F401


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

    engine = create_async_engine(async_url, pool_size=4, max_overflow=2)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 2: Smoke-test the fixture with a trivial pg test**

Create a temporary test file `server/tests/test_pg_fixture_smoke.py` to confirm the container boots and the engine works:

```python
import pytest
from sqlalchemy import text


@pytest.mark.pg
@pytest.mark.asyncio
async def test_pg_engine_smoke(pg_engine):
    async with pg_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
```

- [ ] **Step 3: Run the smoke test**

```bash
cd server && uv run pytest -m pg tests/test_pg_fixture_smoke.py -v
```

Expected: ~5-10s startup (Docker pulls postgres:16-alpine if not cached), then 1 passed.

If Docker is not running, expected error: `docker.errors.DockerException: Error while fetching server API version` — the engineer must start Docker Desktop / colima / podman-docker-shim, then re-run.

- [ ] **Step 4: Delete the smoke test file**

The smoke test served only to validate the fixture. Remove it:

```bash
rm server/tests/test_pg_fixture_smoke.py
```

- [ ] **Step 5: Re-run the default suite to confirm nothing regressed**

```bash
cd server && uv run pytest -q
```

Expected: all 133+ tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/tests/conftest_pg.py
git commit -m "$(cat <<'EOF'
test(server): add Postgres testcontainer fixture (pg_engine)

Session-scoped postgres:16-alpine container; per-test engine with
fresh schema (create_all/drop_all). Exposes engine, not session,
so concurrent tests can build their own session factories on
separate connections.
EOF
)"
```

---

## Task 3: Write the failing concurrent race test + implement the lock + verify GREEN

This task bundles RED → GREEN → commit because the assertion in the test only makes sense once the lock exists. Run the test before each implementation step to watch it go from FAIL → PASS.

**Files:**
- Create: `server/tests/test_memory_mirror_concurrent_pg.py`
- Modify: `server/app/services/memory_mirror.py`

### 3a. Write the concurrent race test (RED)

- [ ] **Step 1: Write the test file**

Create `server/tests/test_memory_mirror_concurrent_pg.py` with this exact content:

```python
"""Concurrent-race regression test for memory_mirror.sync_user.

Without the advisory lock, two simultaneous sync_user() calls for the
same user_id will both SELECT-then-INSERT for the same (user_id, ticker,
trade_date) triples and the second commit raises IntegrityError on the
uq_memory_entry_user_ticker_date constraint. With the lock, the second
caller acquires nothing, logs a warning, and returns 0.

Asyncio's cooperative scheduling guarantees the race: every per-entry
`await session.execute(SELECT ...)` is a yield point where the two
coroutines interleave. No monkeypatching needed to force overlap.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.memory_entry import MemoryEntry
from app.models.user import User
from app.services.memory_mirror import sync_user

FIXTURE = Path(__file__).parent / "fixtures" / "trading_memory_mixed.md"
N_ENTRIES = 3  # 2 resolved + 1 pending; malformed entry in fixture is skipped


async def _seed(pg_engine, tmp_path) -> uuid.UUID:
    """Insert a User row and write the trading_memory.md fixture to disk.

    Returns the user_id. Uses a one-shot session, then closes it so the
    race coroutines start from a clean slate.
    """
    uid = uuid.uuid4()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=uid, github_id=f"gh-race-{uid}"))
        await s.commit()

    mem_dir = tmp_path / "users" / str(uid) / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "trading_memory.md").write_text(FIXTURE.read_text(encoding="utf-8"))
    return uid


@pytest.mark.pg
@pytest.mark.asyncio
async def test_concurrent_sync_serializes_via_advisory_lock(
    pg_engine, tmp_path, caplog,
):
    uid = await _seed(pg_engine, tmp_path)
    caplog.set_level(logging.WARNING, logger="app.services.memory_mirror")

    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def one_sync() -> int | BaseException:
        async with factory() as s:
            try:
                return await sync_user(s, dashboard_dir=tmp_path, user_id=uid)
            except BaseException as e:  # noqa: BLE001 -- test wants to see ANY failure
                return e

    a, b = await asyncio.gather(one_sync(), one_sync())

    # GREEN expectation: one caller acquires the lock and processes all
    # N entries; the other sees the lock held and returns 0.
    # RED expectation (no lock): one returns N, the other raises
    # IntegrityError on commit due to uq_memory_entry_user_ticker_date.
    assert not isinstance(a, BaseException), f"sync_user raised: {a!r}"
    assert not isinstance(b, BaseException), f"sync_user raised: {b!r}"
    assert sorted([a, b]) == [0, N_ENTRIES], (
        f"expected one sync to win (returned {N_ENTRIES}) and one to skip "
        f"(returned 0); got {a=} {b=}. If both are {N_ENTRIES}, the lock "
        f"is not preventing the race. If one is an exception, the test's "
        f"BaseException guard failed."
    )

    # The skipped caller logged the expected warning.
    skip_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "skipped" in r.message and str(uid) in r.message
    ]
    assert len(skip_warnings) == 1, (
        f"expected exactly one 'skipped' WARNING mentioning user_id={uid}, "
        f"got: {[r.message for r in caplog.records]}"
    )

    # No duplicate rows — uq_memory_entry_user_ticker_date upheld.
    async with factory() as s:
        rows = (
            await s.execute(select(MemoryEntry).where(MemoryEntry.user_id == uid))
        ).scalars().all()
    assert len(rows) == N_ENTRIES, (
        f"expected exactly {N_ENTRIES} rows for user {uid}, got {len(rows)} "
        f"(duplicates indicate the lock failed)"
    )
```

- [ ] **Step 2: Run the test — confirm RED**

```bash
cd server && uv run pytest -m pg tests/test_memory_mirror_concurrent_pg.py -v
```

Expected: FAIL. The most likely failure mode is one of:

1. `AssertionError: sync_user raised: IntegrityError(...) ...` — second commit hit the unique constraint.
2. `AssertionError: expected one sync to win ... and one to skip; got a=3 b=3` — both raced through cleanly (unlikely under asyncio interleaving, but possible if all 3 entries already happened to be in different states).

Either failure mode confirms the lock is missing. If by an extremely unlucky scheduling the test passes (`[0, 3]` returned without any lock), the engineer should re-run 3-5 times to verify — but this should not happen in practice with N=3 entries and asyncio's per-await yield behavior.

### 3b. Implement the advisory lock (GREEN)

- [ ] **Step 3: Read the current top of `memory_mirror.py`**

Open `server/app/services/memory_mirror.py`. The current imports + module-level constants:

```python
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.services.user_root import user_results_dir

logger = logging.getLogger(__name__)
```

And the current top of `sync_user`:

```python
async def sync_user(
    session: AsyncSession,
    *,
    dashboard_dir: Path,
    user_id: uuid.UUID,
) -> int:
    """Upsert every entry from the user's disk log into memory_entries.

    Returns the number of entries processed (inserted + updated, ignoring
    malformed entries the parser already skipped).
    """
    path = _memory_log_path(dashboard_dir, user_id)
    parsed = _parse_disk(path)
    if not parsed:
        return 0
```

- [ ] **Step 4: Add the lock primitives at module scope**

Edit `server/app/services/memory_mirror.py`. Add to the imports:

```python
import hashlib
import struct

from sqlalchemy import select, text
```

(Note: `text` is added to the existing `from sqlalchemy import select` line.)

Then add right after `logger = logging.getLogger(__name__)`:

```python
# Postgres advisory-lock namespace for memory_mirror.sync_user races.
# Two-key form: (NAMESPACE, signed_int32_from_user_uuid). Greppable in
# pg_locks as classid=0x4D4D5252 ("MMRR"). See spec §3.
_LOCK_NAMESPACE = 0x4D4D5252


def _user_key(user_id: uuid.UUID) -> int:
    """Map a user UUID to a signed int32 advisory-lock key (deterministic)."""
    # Python's built-in hash() is randomized per-process; BLAKE2 is
    # deterministic — required so two workers compute the same key.
    digest = hashlib.blake2b(user_id.bytes, digest_size=4).digest()
    return struct.unpack(">i", digest)[0]


async def _try_acquire(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Try to acquire the per-user advisory lock for this transaction.

    Returns True on Postgres if the lock is acquired (or always True on
    non-Postgres dialects — the lock is a no-op for SQLite test runs).
    The lock auto-releases on COMMIT / ROLLBACK.
    """
    bind = session.bind
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name != "postgresql":
        return True
    row = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:ns, :uid)"),
        {"ns": _LOCK_NAMESPACE, "uid": _user_key(user_id)},
    )
    return bool(row.scalar())
```

- [ ] **Step 5: Wrap `sync_user` body with the lock acquisition**

In `server/app/services/memory_mirror.py`, replace the existing top of `sync_user`:

```python
async def sync_user(
    session: AsyncSession,
    *,
    dashboard_dir: Path,
    user_id: uuid.UUID,
) -> int:
    """Upsert every entry from the user's disk log into memory_entries.

    Returns the number of entries processed (inserted + updated, ignoring
    malformed entries the parser already skipped).
    """
    path = _memory_log_path(dashboard_dir, user_id)
    parsed = _parse_disk(path)
    if not parsed:
        return 0
```

…with:

```python
async def sync_user(
    session: AsyncSession,
    *,
    dashboard_dir: Path,
    user_id: uuid.UUID,
) -> int:
    """Upsert every entry from the user's disk log into memory_entries.

    Returns the number of entries processed (inserted + updated, ignoring
    malformed entries the parser already skipped). Returns 0 if another
    caller holds the per-user advisory lock — the in-flight sync will
    cover the work; this caller no-ops with a warning. See spec §6.

    Concurrency contract is exercised by tests/test_memory_mirror_
    concurrent_pg.py — run `cd server && uv run pytest -m pg` before
    opening a PR that touches this file.
    """
    if not await _try_acquire(session, user_id):
        logger.warning(
            "memory_mirror sync skipped for user_id=%s — lock held by another sync",
            user_id,
        )
        return 0

    path = _memory_log_path(dashboard_dir, user_id)
    parsed = _parse_disk(path)
    if not parsed:
        return 0
```

(Note: the lock acquire happens before `_parse_disk` so that we don't even read disk if we're going to skip. Order is: acquire → parse → upsert → commit.)

- [ ] **Step 6: Run the concurrent test — verify GREEN**

```bash
cd server && uv run pytest -m pg tests/test_memory_mirror_concurrent_pg.py -v
```

Expected: PASS. The test now sees `[0, 3]` results, one WARNING with "skipped" and the user_id, and 3 rows.

- [ ] **Step 7: Run the full default suite — verify no SQLite regression**

```bash
cd server && uv run pytest -q
```

Expected: all 133+ tests pass. Critical: the four existing tests in `tests/test_memory_mirror.py` must pass unmodified — they prove the dialect-gate works (SQLite returns True from `_try_acquire`, so the function behaves identically to today).

- [ ] **Step 8: Run the entire pg suite — verify everything is green together**

```bash
cd server && uv run pytest -m 'pg or not pg' -q
```

Expected: all 133+ SQLite tests + 1 pg test pass.

- [ ] **Step 9: Verify no diff in callers**

The spec promises caller behavior is unchanged. Confirm:

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git diff --stat HEAD server/app/workers/tasks.py server/app/routers/portfolio.py
```

Expected: empty output. If non-empty, the implementation drifted from the spec — investigate.

- [ ] **Step 10: Lint pass**

```bash
cd server && uv run ruff check app/services/memory_mirror.py tests/test_memory_mirror_concurrent_pg.py tests/conftest_pg.py
```

Expected: `All checks passed!`. Common slips: missing `from __future__ import annotations`, unused import, `S608` if the SQL `text()` looks like injection (it doesn't — params are bound).

- [ ] **Step 11: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/services/memory_mirror.py server/tests/test_memory_mirror_concurrent_pg.py
git commit -m "$(cat <<'EOF'
fix(server): advisory lock around memory_mirror.sync_user (v3+ #1)

Wraps sync_user with pg_try_advisory_xact_lock keyed on (NAMESPACE,
blake2b(user_id)). Second concurrent caller logs a warning and returns
0 instead of racing into IntegrityError on uq_memory_entry_user_ticker_date.

- Dialect-gated: no-op on SQLite (preserves existing 133-test suite).
- Transaction-scoped lock: auto-releases on COMMIT/ROLLBACK.
- Zero caller diff: worker + portfolio routers already tolerate
  processed == 0; centralized inside sync_user.

Concurrent race verified by tests/test_memory_mirror_concurrent_pg.py
(run via `pytest -m pg`).

Implements spec §6 deferred from PR #3.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Verification (final goal-backward check)

Before declaring done, an engineer (or `gsd-verifier` subagent) confirms each:

- [ ] **V1 — SQLite suite unchanged.** `cd server && uv run pytest -q` shows all 133+ tests pass, no skipped tests beyond the new `pg`-marked one.
- [ ] **V2 — Postgres concurrent test passes.** `cd server && uv run pytest -m pg -v` shows `test_concurrent_sync_serializes_via_advisory_lock PASSED`.
- [ ] **V3 — Combined run.** `cd server && uv run pytest -m 'pg or not pg' -q` — both suites green together.
- [ ] **V4 — No caller diff.** `git diff main..HEAD -- server/app/workers/tasks.py server/app/routers/portfolio.py` is empty.
- [ ] **V5 — Lock present before any read.** Read `server/app/services/memory_mirror.py` and confirm: the `async def sync_user(...)` body's **first** statement (after the docstring) is the `if not await _try_acquire(...): ... return 0` block. The `_memory_log_path` / `_parse_disk` / `await session.execute(select(...))` calls all come after.
- [ ] **V6 — Warning text matches.** A `grep -n "skipped" server/app/services/memory_mirror.py` finds exactly one occurrence, in the lock-held branch.
- [ ] **V7 — Ruff clean.** `cd server && uv run ruff check` reports `All checks passed!`.
- [ ] **V8 — Spec sections covered.** Map each spec section to a task:
  - §2 Architecture → Task 3 step 5
  - §3.1 Lock primitive → Task 3 step 4 (the `text("SELECT pg_try_advisory_xact_lock...")` line)
  - §3.2 Lock key derivation → Task 3 step 4 (`_user_key`)
  - §3.3 Dialect handling → Task 3 step 4 (`_try_acquire` early return)
  - §4 Caller behavior unchanged → V4
  - §5.1 Existing tests preserved → V1
  - §5.2 New concurrent test → Task 3a
  - §5.4 Testcontainer fixture → Task 2
  - §5.5 Dependencies → Task 1
  - §6 Files touched → all of Tasks 1-3

If V1-V8 all pass, the implementation is done.

---

## Out-of-scope reminders

These are deliberately NOT done by this plan (per spec §2):

- Worker-side `_sync_user_safe` rollback wrapper.
- Switching to `INSERT ... ON CONFLICT DO UPDATE`.
- Reducing per-request sync frequency in `portfolio.py`.
- Items #2 (RESOLVED+raw_return invariant) and #3 (DecisionPin invariant).
- CI wiring (repo has no `.github/workflows/` yet).

If discovered during implementation, file as new followups — do not bundle.

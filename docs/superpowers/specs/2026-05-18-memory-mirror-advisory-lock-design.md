# `memory_mirror` Postgres Advisory Lock — Design

**Status:** Approved, awaiting implementation plan
**Date:** 2026-05-18
**Followup of:** PR #3 (Wave 3 — Portfolio P&L); spec §6 (`docs/superpowers/specs/2026-05-17-trading-dashboard-design.md`)
**Author:** erik

---

## 1. Problem

`memory_mirror.sync_user()` reads the user's `trading_memory.md` from disk, then for each entry performs a `SELECT … WHERE (user_id, ticker, trade_date)` followed by an `INSERT` or `UPDATE` on `memory_entries`, then a single `COMMIT`.

The table has a unique constraint `uq_memory_entry_user_ticker_date` on `(user_id, ticker, trade_date)`. Two callers running concurrently for the same user can interleave:

1. Worker post-run sync (after every successful run; `server/app/workers/tasks.py:233`).
2. Per-request fallback sync, called from each of the three portfolio routers (`/portfolio/summary`, `/portfolio/curve`, `/portfolio/ticker/{ticker}`).

Two of those calls landing in the same millisecond — easy when a UI poll arrives while a worker run finishes — produce one of:

- `IntegrityError` on the second `INSERT`. Router caller is wrapped in `_sync_user_safe`, which catches `SQLAlchemyError`, rolls back, and logs a warning — so it manifests as "stale read with a warning log", not a 500. Worker caller is wrapped only in `logger.exception`, so it logs but the worker carries on.
- Duplicate rows if the unique constraint were ever removed. Today it's not, so this is mitigated.

The spec §6 already prescribed the fix:

> Race between simultaneous syncs → Postgres advisory lock keyed on `('memory_mirror', user_id)`; second sync no-ops with a warning.

It was deferred from Wave 3 to ship the rest of the wave on schedule. This spec implements it.

---

## 2. Goal & non-goals

**Goal.** Eliminate the race by serializing concurrent `sync_user` calls for the same user via a Postgres advisory lock. The "second" caller observes the lock is held, logs a warning, and returns 0 — the data is being synced by someone else; the next call wins.

**Non-goals (deliberately).**

- **Switch to `INSERT … ON CONFLICT DO UPDATE`.** A different way to remove the race, but a larger semantic change (UPSERT vs. read-modify-write). Out of scope.
- **Rework the per-request mirror sync** that the wave-3 review flagged as a perf concern (`server/app/routers/portfolio.py` calling `_sync_user_safe` on every API call). The lock makes the redundant syncs *correct*; reducing them is a separate followup.
- **Add a worker-side `_sync_user_safe`-style rollback wrapper.** The worker's current `logger.exception` is acceptable because the run already succeeded; mirror failure is non-fatal and recoverable on the next request-side sync.
- **Bundle the deferred `MemoryEntry.status=RESOLVED + raw_return=None` invariant (#2) or `DecisionPin` cross-field invariant (#3).** Separate followups in PR #3's body.
- **Add a metric / counter for skipped syncs.** No metrics infra exists. `logger.warning` is sufficient for v1.

---

## 3. Architecture

The lock acquisition lives **inside `sync_user`**, at the top of the function before any reads. Single point of correctness: all current and future callers are automatically protected without a per-site diff.

```python
NAMESPACE = 0x4D4D5252  # "MMRR" — greppable in pg_locks

async def sync_user(session, *, dashboard_dir, user_id) -> int:
    if not await _try_acquire(session, user_id):
        logger.warning(
            "memory_mirror sync skipped for user_id=%s — lock held by another sync",
            user_id,
        )
        return 0
    # ... existing parse + upsert + commit logic, unchanged ...
```

### 3.1 Lock primitive

`pg_try_advisory_xact_lock(int, int)`, transaction-scoped:

- **Non-blocking.** Spec semantic is "no-op with warning", not "wait then sync"; `try_` is the right variant.
- **Transaction-scoped.** Auto-releases on `COMMIT`/`ROLLBACK`. No explicit unlock, no leak path on exception.
- **Two-key form.** First key is a fixed namespace constant per lock-purpose so `SELECT * FROM pg_locks` is greppable by operators.

### 3.2 Lock key derivation

```python
import hashlib
import struct

def _user_key(user_id: uuid.UUID) -> int:
    h = hashlib.blake2b(user_id.bytes, digest_size=4).digest()
    return struct.unpack(">i", h)[0]  # signed int32, fits pg_try_advisory_xact_lock arg
```

- **BLAKE2 (not Python `hash`)**: deterministic across processes. Python's built-in `hash()` is randomized per-process — two workers would compute different keys for the same UUID and the lock would not contend.
- **Collision probability ~1-in-2³² per pair of users.** A collision causes a spurious skip on one user when an unrelated user is mid-sync — never a correctness bug, only a latency bump. Acceptable for short-lived sync work.

### 3.3 Dialect handling

```python
async def _try_acquire(session: AsyncSession, user_id: uuid.UUID) -> bool:
    if session.bind.dialect.name != "postgresql":
        return True  # SQLite test path — advisory locks don't exist
    row = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:ns, :uid)"),
        {"ns": NAMESPACE, "uid": _user_key(user_id)},
    )
    return bool(row.scalar())
```

The 133-test SQLite-in-memory suite is preserved as-is. The lock is a no-op there, which means:

- ✅ Existing `test_memory_mirror.py` tests still pass without modification.
- ⚠️ The lock acquisition is **not exercised by the default test suite**. This is mitigated by the dedicated Postgres-backed concurrency test (§5).

---

## 4. Caller behavior — unchanged

| Call site | File:line | Behavior on skip |
|-----------|-----------|------------------|
| Worker post-run | `server/app/workers/tasks.py:233` | Sees `processed == 0`; no exception; existing `try/except logger.exception` covers any other error. Next request-side sync will resync. |
| `/portfolio/summary` | `server/app/routers/portfolio.py:96` (via `_sync_user_safe`) | Sees `0` returned; serves whatever is already in Postgres. Already tolerated this case for any other no-op. |
| `/portfolio/curve` | `server/app/routers/portfolio.py:107` | Same as above. |
| `/portfolio/ticker/{ticker}` | `server/app/routers/portfolio.py:120` | Same as above. |

No call-site diff is required. This is the load-bearing reason for centralizing inside `sync_user`.

---

## 5. Tests

### 5.1 Existing SQLite suite — preserved unchanged

The four tests in `server/tests/test_memory_mirror.py` continue to pass without modification. They verify that the existing return-value contract (`processed: int`), upsert behavior, and idempotency are unaffected by adding the lock-acquire step (which is a no-op on SQLite).

### 5.2 New Postgres concurrency test — `server/tests/test_memory_mirror_concurrent_pg.py`

Marked `@pytest.mark.pg`. Uses a Postgres testcontainer (§5.4) and asserts the race is actually serialized.

**Race creation.** A bare `asyncio.gather(sync_user(...), sync_user(...))` is not sufficient — the two coroutines could complete serially without overlap, both succeed, and the test would pass for the wrong reason. The test must force overlap. The cleanest way: monkeypatch `memory_mirror._parse_disk` to await an `asyncio.Event` between read and return on the *first* call, then `set()` the event after observing both calls have entered. This guarantees the lock is held when the second caller tries to acquire.

```python
@pytest.mark.pg
@pytest.mark.asyncio
async def test_concurrent_sync_skips_with_warning(
    pg_engine, tmp_path, caplog, monkeypatch,
):
    uid = uuid.uuid4()
    # ... seed User row + write disk memory log with N=3 entries via fixture helper ...

    # Force the race window
    entered = asyncio.Event()
    release_first = asyncio.Event()
    first_call = True
    real_parse = memory_mirror._parse_disk

    def slow_parse(path):
        nonlocal first_call
        if first_call:
            first_call = False
            # Run the parse, then await release inside the locked transaction.
            # Wrapping is done by patching _try_acquire instead — see plan.
        return real_parse(path)
    # (Final shape is decided in the implementation plan; the design
    # contract is: "second caller arrives while first holds the lock".)

    sess_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async def run_one(delay=0):
        async with sess_factory() as s:
            if delay:
                await asyncio.sleep(delay)
            return await sync_user(s, dashboard_dir=tmp_path, user_id=uid)

    a, b = await asyncio.gather(run_one(0), run_one(0.05))

    # One wins (returns N), one skips (returns 0). Order is not guaranteed.
    assert sorted([a, b]) == [0, 3]
    assert any("skipped" in r.message and str(uid) in r.message
               for r in caplog.records)

    # Single source of truth check: no duplicate rows
    async with sess_factory() as s:
        rows = (await s.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == uid)
        )).scalars().all()
    assert len(rows) == 3
```

The exact synchronization primitive (event-vs-sleep, patch site, etc.) is an implementation detail the plan will settle. The **design contract** is: the test must reliably force the second caller to attempt acquisition while the first holds the lock, then assert the skip+warn+no-duplicate behavior.

### 5.3 Optional smoke test — `test_advisory_lock_invoked_pg`

A single-call test that asserts `pg_try_advisory_xact_lock` is actually invoked under Postgres (catches future dialect-detection regressions). Cheap insurance.

### 5.4 Testcontainer fixture — `server/tests/conftest_pg.py`

New file containing a session-scoped Postgres container and an engine fixture. The concurrent test in §5.2 needs **two sessions on two connections** (a single session can't deadlock against itself on advisory locks), so the fixture exposes the engine, not a session — callers build their own session factory.

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from app.models.base import Base
from app.models import user as _user, run as _run, memory_entry as _me  # noqa: F401


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture
async def pg_engine(pg_container):
    url = pg_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://", 1
    )
    engine = create_async_engine(url, pool_size=4, max_overflow=2)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- Marker `pg` is registered in `pyproject.toml` and skipped by default. Opt-in: `pytest -m pg`.
- Local dev runs `pytest` as today (SQLite only) → no behavioral change for contributors without Docker.
- CI gets a new `pg` job that runs `pytest -m pg` on every push.

### 5.5 Dependencies

- `testcontainers[postgres]` added to `server/pyproject.toml` dev dependencies.
- No production dependency changes.

---

## 6. Files touched

| File | Change |
|------|--------|
| `server/app/services/memory_mirror.py` | Add `NAMESPACE`, `_user_key`, `_try_acquire`. Wrap `sync_user` body. |
| `server/tests/conftest_pg.py` | NEW. Testcontainer fixture. |
| `server/tests/test_memory_mirror_concurrent_pg.py` | NEW. Concurrent skip + no-duplicate test (+ optional invocation smoke test). |
| `server/pyproject.toml` | Add `testcontainers[postgres]` dev dep; register `pg` pytest marker. |
| `.github/workflows/*` | Add (or extend) a CI job that runs `pytest -m pg`. |

No Alembic migration. No production dependency changes. No frontend changes. No spec changes elsewhere — this implements §6.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **Lock not exercised in default test suite.** Dialect-gate means SQLite returns `True` unconditionally. | Dedicated `-m pg` test that fires a real concurrent race. Required to pass in CI. |
| **Key collision causes spurious skip.** Two unrelated users mapping to same int32 → one user's sync skips while the other's is in flight. | Probability ≈ 1/2³² per pair; cost of collision is one extra warning log + a redelayed sync, not a correctness bug. Accept. |
| **Testcontainer adds Docker dep for new contributors.** | `-m pg` is opt-in. Default `pytest` still works without Docker. Document in `server/README.md` (or wherever test instructions live). |
| **CI duration increases.** | Postgres container starts in ~3-5s; the concurrency test runs in <1s. Net ~5-10s added to CI. |
| **`session.bind.dialect.name` returns `None` in some async-session edge case.** | Defensive: `getattr(session.bind, "dialect", None) and session.bind.dialect.name == "postgresql"`. Falls open on detection failure (treats unknown as not-Postgres → no-op acquire) which is consistent with the SQLite path. |

---

## 8. Verification criteria

The implementation is done when all of the following are true:

1. `cd server && uv run pytest` (SQLite default) — all 133+ existing tests pass.
2. `cd server && uv run pytest -m pg` — new concurrent test passes; asserts one of two concurrent `sync_user(...)` returns N, the other returns 0, warning is logged, no duplicate rows.
3. CI's new `pg` job is green.
4. Manual code review confirms `_try_acquire` is called before any `SELECT` / `INSERT` in `sync_user`.
5. No diff in `server/app/workers/tasks.py` or `server/app/routers/portfolio.py` — caller behavior is genuinely unchanged.

---

## 9. References

- Spec §6 (Error Handling → Memory mirror): `docs/superpowers/specs/2026-05-17-trading-dashboard-design.md`
- Wave 3 plan: `docs/superpowers/plans/2026-05-18-trading-dashboard-wave-3.md`
- Postgres advisory locks: https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS
- PR #3 body (v3+ followups list): `gh pr view 3`

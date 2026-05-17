# `MemoryEntry.status=RESOLVED ⟹ raw_return NOT NULL` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `(status=RESOLVED, raw_return=NULL)` unrepresentable in `memory_entries`. Convert the existing parse-failure code path in `memory_mirror.sync_user` from "silently insert bad row" → "demote to PENDING + warn". Remove the now-dead defensive filter in `portfolio_calc._resolved_pnls`.

**Architecture:** One DB CHECK constraint (`ck_memory_entry_resolved_has_raw_return`) declared on `MemoryEntry.__table_args__` and mirrored in a new alembic migration with a backfill `UPDATE` for any pre-existing violating rows. One ~6-line addition to `sync_user` that detects the demote case at the data boundary. One ~3-line removal in `_resolved_pnls` plus a docstring rewrite. Cross-dialect-safe (works in both Postgres and SQLite).

**Tech Stack:** Python 3.10+, SQLAlchemy 2.0 async, alembic, pytest-asyncio, SQLite (test) + Postgres 16 (prod).

**Spec:** `docs/superpowers/specs/2026-05-18-memory-entry-resolved-invariant-design.md`

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `server/app/models/memory_entry.py` | MODIFY | Add `CheckConstraint` to `__table_args__`. |
| `server/alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py` | CREATE | New migration: backfill demote + add CHECK constraint. |
| `server/app/services/memory_mirror.py` | MODIFY | Add ~6-line demote-to-PENDING block inside the upsert loop. |
| `server/app/services/portfolio_calc.py` | MODIFY | Remove `if r is None: continue` + update `_resolved_pnls` docstring. |
| `server/tests/fixtures/trading_memory_resolved_unparseable.md` | CREATE | New disk fixture with a resolved entry whose raw value is malformed. |
| `server/tests/test_portfolio_router.py` | MODIFY | Change `_add_entry` default from `raw=None` to `raw=0.0`. |
| `server/tests/test_models.py` | MODIFY | Add IntegrityError test for the CHECK constraint. |
| `server/tests/test_memory_mirror.py` | MODIFY | Add demote-on-parse-failure test using the new fixture. |
| `server/tests/test_migration_resolved_check.py` | CREATE | Migration backfill smoke test (calls the migration's `upgrade()` against a hand-built pre-constraint table). |

No frontend changes. No Pydantic schema changes. No new production dependencies. No diff to `server/app/workers/tasks.py`, `server/app/routers/portfolio.py`, or `server/app/schemas/portfolio.py`.

---

## Task 1: DB CHECK constraint + alembic migration + ORM-rejection test + migration smoke test

**Files:**
- Modify: `server/app/models/memory_entry.py`
- Create: `server/alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py`
- Modify: `server/tests/test_models.py`
- Create: `server/tests/test_migration_resolved_check.py`

This task is RED (failing ORM test) → GREEN (add CheckConstraint + migration) → migration smoke verification → commit.

### 1a. Write the failing ORM-rejection test

- [ ] **Step 1: Open `server/tests/test_models.py`** to confirm the existing test patterns.

Existing file uses the `db_session` fixture from `tests/conftest.py` which creates a fresh in-memory SQLite engine and calls `Base.metadata.create_all`. New tests follow the same shape.

- [ ] **Step 2: Append a new test to `server/tests/test_models.py`**

Add this test at the end of the file (preserving existing tests + imports — only add):

```python
import pytest
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_resolved_without_raw_return_rejected(db_session):
    """ck_memory_entry_resolved_has_raw_return enforces the invariant:
    status=RESOLVED ⟹ raw_return IS NOT NULL.
    """
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-ck"))
    await db_session.flush()

    db_session.add(
        MemoryEntry(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-09",
            rating="Buy",
            status=MemoryEntryStatus.RESOLVED,
            raw_return=None,  # ← violates the invariant
            alpha_return=None,
            holding_days=None,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
```

(Only add the new test + the `IntegrityError` import — do NOT add the `pytest`/`uuid`/model imports if they're already there. Check the top of the file first.)

- [ ] **Step 3: Run test to verify it FAILS (RED)**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_models.py::test_resolved_without_raw_return_rejected -v
```

Expected: `FAILED — DID NOT RAISE <class 'sqlalchemy.exc.IntegrityError'>`. The flush succeeds because no constraint exists yet.

### 1b. Add the CheckConstraint to the model (GREEN — part 1)

- [ ] **Step 4: Modify `server/app/models/memory_entry.py`**

Find the imports block (currently includes `UniqueConstraint`). Add `CheckConstraint`:

```python
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
```

Find the `__table_args__` tuple:

```python
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ticker", "trade_date", name="uq_memory_entry_user_ticker_date"
        ),
    )
```

Replace it with:

```python
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ticker", "trade_date", name="uq_memory_entry_user_ticker_date"
        ),
        CheckConstraint(
            "status != 'RESOLVED' OR raw_return IS NOT NULL",
            name="ck_memory_entry_resolved_has_raw_return",
        ),
    )
```

**Important — enum value casing.** The CHECK SQL uses `'RESOLVED'` (uppercase) because SQLAlchemy stores `Enum(MemoryEntryStatus, ...)` columns by member **name** (uppercase), not value (lowercase). The existing migration `a1b2c3d4e5f6` declares the enum type as `sa.Enum('PENDING', 'RESOLVED', name='memory_entry_status')` — same uppercase. The Pydantic API output uses `.value` (lowercase) to convert. The CHECK must match the DB-stored representation: uppercase. If you write `'resolved'` it will silently always-allow.

- [ ] **Step 5: Run the test again — verify GREEN**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_models.py::test_resolved_without_raw_return_rejected -v
```

Expected: `PASSED`. The CHECK constraint is now defined on the in-memory SQLite schema (via `create_all`).

- [ ] **Step 6: Run the full default suite — verify no SQLite regression**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
```

Expected: all existing tests + the new one pass. There should be 134 passing (133 from PR #3's baseline + 1 new).

### 1c. Add the alembic migration (GREEN — part 2)

The model change above only fires for tests (`Base.metadata.create_all`). Production uses migrations. Without a corresponding migration, deployed Postgres DBs would never get the constraint.

- [ ] **Step 7: Create `server/alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py`**

Write this exact content:

```python
"""memory_entry_resolved_check

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-18 00:00:00.000000

Backfills any pre-existing (status=RESOLVED, raw_return IS NULL) rows by
demoting status to PENDING, then adds the
ck_memory_entry_resolved_has_raw_return CHECK constraint so the bad state
becomes unrepresentable. See spec §5.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Backfill: existing RESOLVED rows with NULL raw_return are by definition
    # parse-failures that snuck through. Demote to PENDING so the constraint
    # can be applied. Re-sync from disk recovers proper RESOLVED status
    # once the disk markdown is corrected.
    op.execute(
        "UPDATE memory_entries "
        "SET status = 'PENDING' "
        "WHERE status = 'RESOLVED' AND raw_return IS NULL"
    )
    with op.batch_alter_table("memory_entries") as batch:
        batch.create_check_constraint(
            "ck_memory_entry_resolved_has_raw_return",
            "status != 'RESOLVED' OR raw_return IS NOT NULL",
        )


def downgrade() -> None:
    """Downgrade schema.

    No reverse backfill — once a row is demoted to PENDING in upgrade(),
    downgrade cannot infer the original raw_return value.
    """
    with op.batch_alter_table("memory_entries") as batch:
        batch.drop_constraint(
            "ck_memory_entry_resolved_has_raw_return", type_="check"
        )
```

- [ ] **Step 8: Verify the migration imports cleanly**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run python -c "
import importlib.util
spec = importlib.util.spec_from_file_location(
    'm', 'alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py'
)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('revision=', m.revision, 'down_revision=', m.down_revision)
print('upgrade=', m.upgrade); print('downgrade=', m.downgrade)
"
```

Expected: prints `revision= b1c2d3e4f5a6 down_revision= a1b2c3d4e5f6` and the two function objects. No syntax errors.

- [ ] **Step 9: Verify alembic recognizes the new migration in the chain**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && DATABASE_URL=sqlite+aiosqlite:///:memory: uv run alembic heads
```

Expected: prints `b1c2d3e4f5a6 (head)`. If it shows `a1b2c3d4e5f6` or two heads, the new migration is missing or its `down_revision` is wrong.

### 1d. Add migration backfill smoke test

- [ ] **Step 10: Create `server/tests/test_migration_resolved_check.py`**

This test verifies the migration's backfill SQL works in isolation — without invoking the full alembic runtime (which requires more setup than is justified here). It hand-builds a `memory_entries` table without the CHECK, inserts a violating row, then invokes the migration's `upgrade()` function and asserts (a) the row was demoted and (b) the constraint now rejects new violators.

Write this exact content:

```python
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
        # Minimal pre-migration shape — only the columns the backfill UPDATE
        # touches. The status column is a plain TEXT (matches what
        # sa.Enum produces on SQLite). No FK / index / unique needed for
        # this test.
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

    # Run the migration's upgrade() against a sync connection wrapped from async.
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
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO memory_entries (id, status, raw_return) "
                "VALUES (:id, 'RESOLVED', NULL)"
            ), {"id": str(uuid.uuid4())})
```

- [ ] **Step 11: Run the migration smoke test**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_migration_resolved_check.py -v
```

Expected: `1 passed`. Verifies the migration's backfill + constraint creation both work end-to-end against SQLite.

### 1e. Final Task 1 verification

- [ ] **Step 12: Run the full default suite**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
```

Expected: 133 (existing) + 1 (ORM-rejection) + 1 (migration smoke) = **135 passed**.

- [ ] **Step 13: Lint pass**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/models/memory_entry.py alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py tests/test_models.py tests/test_migration_resolved_check.py
```

Expected: `All checks passed!`.

- [ ] **Step 14: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/models/memory_entry.py \
        server/alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py \
        server/tests/test_models.py \
        server/tests/test_migration_resolved_check.py
git commit -m "$(cat <<'EOF'
feat(server): CHECK constraint — RESOLVED ⟹ raw_return NOT NULL

ck_memory_entry_resolved_has_raw_return on memory_entries makes
(status=RESOLVED, raw_return IS NULL) unrepresentable.

- Model: CheckConstraint in MemoryEntry.__table_args__ (string form
  matches enum-by-name storage: 'RESOLVED' uppercase, not 'resolved').
- Migration b1c2d3e4f5a6: backfills any existing violating rows to
  status=PENDING, then adds the constraint via batch_alter_table for
  cross-dialect (SQLite + Postgres) safety.
- Tests: ORM-level IntegrityError + migration backfill smoke test.

Implements spec §4-5 of v3+ followup #2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `memory_mirror.sync_user` demote-to-PENDING on parse failure

**Files:**
- Create: `server/tests/fixtures/trading_memory_resolved_unparseable.md`
- Modify: `server/app/services/memory_mirror.py`
- Modify: `server/tests/test_memory_mirror.py`

After Task 1, attempting to upsert a `(RESOLVED, NULL)` row raises `IntegrityError` from the CHECK. This task changes `sync_user` to detect that case earlier and demote to PENDING with a log warning — so the row is still useful (rating, decision text) and the operator sees the parse failure.

### 2a. Create the new fixture file

- [ ] **Step 1: Create `server/tests/fixtures/trading_memory_resolved_unparseable.md`**

This fixture has one non-pending entry whose raw column is `"n/a"` (which `_pct_to_float` returns None for).

```markdown
[2024-05-12 | NVDA | Buy | n/a | n/a | 7d]

DECISION:
NVDA earnings beat — sized up to Buy.

REFLECTION:
Parser couldn't compute return; raw column was 'n/a' in the source.

<!-- ENTRY_END -->
```

(Important: this is a "resolved-shape" entry — 6 pipe-separated fields, no "pending" marker. The parser will set `pending=False` so `sync_user` would normally compute `status=RESOLVED`. But `_pct_to_float("n/a")` returns None, which is the case we want to test.)

### 2b. Write the failing demote test (RED)

- [ ] **Step 2: Append a new test to `server/tests/test_memory_mirror.py`**

Add this test at the end of the file (re-use existing imports — only add `caplog`/`logging` if not present):

```python
import logging


@pytest.mark.asyncio
async def test_sync_demotes_resolved_with_unparseable_raw(
    db_session, tmp_path, caplog,
):
    """Per spec §6: a non-pending entry with unparseable raw must be
    demoted to PENDING (with a warning log) instead of attempting to
    insert a status=RESOLVED, raw_return=NULL row (which the CHECK
    constraint would reject)."""
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-demote"))
    await db_session.flush()

    fixture = (
        Path(__file__).parent / "fixtures"
        / "trading_memory_resolved_unparseable.md"
    )
    mem_dir = tmp_path / "users" / str(uid) / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "trading_memory.md").write_text(fixture.read_text(encoding="utf-8"))

    caplog.set_level(logging.WARNING, logger="app.services.memory_mirror")
    count = await sync_user(db_session, dashboard_dir=tmp_path, user_id=uid)

    assert count == 1
    row = (
        await db_session.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == uid)
        )
    ).scalar_one()
    assert row.status is MemoryEntryStatus.PENDING
    assert row.raw_return is None
    assert row.rating == "Buy"  # rating preserved despite demote

    demote_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "demoting" in r.message
        and "NVDA" in r.message and "2024-05-12" in r.message
    ]
    assert len(demote_warnings) == 1, (
        f"expected exactly one demote WARNING; got: "
        f"{[r.message for r in caplog.records]}"
    )
```

- [ ] **Step 3: Run test to verify it FAILS (RED)**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_memory_mirror.py::test_sync_demotes_resolved_with_unparseable_raw -v
```

Expected: `FAILED` — most likely with an `IntegrityError` from the CHECK constraint added in Task 1 (the unmodified `sync_user` tries to insert `(RESOLVED, NULL)` and the CHECK rejects it). The IntegrityError surfaces because there's no `try/except` in `sync_user` around the commit — the exception propagates out of the test.

This is the right RED signal: the test proves the bad state is no longer silently insertable AND that `sync_user` doesn't yet handle the case gracefully.

### 2c. Implement the demote-to-PENDING block (GREEN)

- [ ] **Step 4: Open `server/app/services/memory_mirror.py`** and find the upsert loop (around lines 92-144 of the current file).

The current code:

```python
        status = MemoryEntryStatus.PENDING if entry.get("pending") else MemoryEntryStatus.RESOLVED
        raw = _pct_to_float(entry.get("raw"))
        alpha = _pct_to_float(entry.get("alpha"))
```

- [ ] **Step 5: Insert the demote check between `raw =` and `alpha =`**

Replace those three lines with:

```python
        status = (
            MemoryEntryStatus.PENDING if entry.get("pending")
            else MemoryEntryStatus.RESOLVED
        )
        raw = _pct_to_float(entry.get("raw"))
        # Spec §6: enforce the (RESOLVED ⟹ raw_return NOT NULL) invariant
        # at the write boundary. If the disk says resolved but the raw
        # value couldn't be parsed, demote to PENDING — the row remains
        # useful (rating, decision text) and the warning surfaces the
        # underlying disk format issue for the operator to fix.
        if status is MemoryEntryStatus.RESOLVED and raw is None:
            logger.warning(
                "memory_mirror: demoting %s/%s to PENDING for user_id=%s — "
                "disk says resolved but raw_return is missing/malformed",
                ticker, trade_date, user_id,
            )
            status = MemoryEntryStatus.PENDING
        alpha = _pct_to_float(entry.get("alpha"))
```

(Nothing else in `sync_user` changes — the existing upsert logic uses the now-possibly-demoted `status` value.)

- [ ] **Step 6: Run the demote test — verify GREEN**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_memory_mirror.py::test_sync_demotes_resolved_with_unparseable_raw -v
```

Expected: `PASSED`. The row is now inserted as PENDING with the expected warning.

- [ ] **Step 7: Run the full default suite — verify no regression**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
```

Expected: 135 (post-Task-1) + 1 (new demote test) = **136 passed**.

The existing 4 tests in `test_memory_mirror.py` use the `trading_memory_mixed.md` fixture, which has no malformed-raw resolved entries (verified — all resolved entries have valid `%` values). They continue to pass.

- [ ] **Step 8: Lint pass**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/services/memory_mirror.py tests/test_memory_mirror.py
```

Expected: `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/services/memory_mirror.py \
        server/tests/test_memory_mirror.py \
        server/tests/fixtures/trading_memory_resolved_unparseable.md
git commit -m "$(cat <<'EOF'
fix(server): demote RESOLVED+unparseable-raw entries to PENDING

sync_user now detects the (status=RESOLVED, raw_return=None) case at
the write boundary and demotes to PENDING with a per-entry WARNING.
Previously this combination snuck through silently and was masked
downstream by _resolved_pnls's defensive filter; with the Task-1 CHECK
constraint in place it would otherwise IntegrityError.

The demote preserves all other entry data (rating, decision text).
Re-syncing after the operator fixes the disk markdown recovers the
proper RESOLVED status.

Implements spec §6 of v3+ followup #2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Remove dead branch in `_resolved_pnls` + test helper cleanup

**Files:**
- Modify: `server/app/services/portfolio_calc.py`
- Modify: `server/tests/test_portfolio_router.py`

With the invariant enforced (Task 1) and the only creation site fixed (Task 2), the defensive `if r is None: continue` filter in `_resolved_pnls` is provably dead code. Removing it strengthens the type-system claim and makes future violations fail loudly with a `TypeError` instead of silently disappearing.

The test helper `_add_entry` in `test_portfolio_router.py` has `raw=None, status=MemoryEntryStatus.RESOLVED` as misleading defaults. No call actually uses them today, but the defaults are a footgun for future test authors (they'd now `IntegrityError`). Fix to safe defaults.

### 3a. Remove the dead branch

- [ ] **Step 1: Open `server/app/services/portfolio_calc.py`** and find `_resolved_pnls` (around lines 37-53).

Current code:

```python
def _resolved_pnls(entries: Iterable[dict[str, Any]]) -> list[tuple[str, str, float]]:
    """Return list of (trade_date, created_at_sort_key, pnl) for resolved entries.

    Skips pending entries and entries with raw_return=None.
    """
    out: list[tuple[str, str, float]] = []
    for e in entries:
        if e.get("status") != "resolved":
            continue
        r = e.get("raw_return")
        if r is None:
            continue
        size = rating_to_size(e.get("rating"))
        sort_key = str(e.get("created_at") or e.get("trade_date") or "")
        out.append((str(e["trade_date"]), sort_key, size * float(r)))
    out.sort(key=lambda t: (t[0], t[1]))
    return out
```

- [ ] **Step 2: Replace with the dead-branch-removed version**

```python
def _resolved_pnls(entries: Iterable[dict[str, Any]]) -> list[tuple[str, str, float]]:
    """Return list of (trade_date, created_at_sort_key, pnl) for resolved entries.

    Skips pending entries. Resolved entries always have raw_return set
    (enforced by ck_memory_entry_resolved_has_raw_return — spec §4).
    A None raw_return on a status='resolved' entry is a contract violation
    and will surface as a TypeError on the size*float(r) below — desirable
    loud-failure behavior, not a regression.
    """
    out: list[tuple[str, str, float]] = []
    for e in entries:
        if e.get("status") != "resolved":
            continue
        r = e.get("raw_return")
        size = rating_to_size(e.get("rating"))
        sort_key = str(e.get("created_at") or e.get("trade_date") or "")
        out.append((str(e["trade_date"]), sort_key, size * float(r)))
    out.sort(key=lambda t: (t[0], t[1]))
    return out
```

(Only two changes: docstring rewrite + remove the `if r is None: continue` block.)

### 3b. Fix the test helper defaults

- [ ] **Step 3: Open `server/tests/test_portfolio_router.py`** and find `_add_entry` (around lines 32-49).

Current:

```python
def _add_entry(session, *, user_id, ticker, trade_date, rating,
               raw=None, status=MemoryEntryStatus.RESOLVED):
```

- [ ] **Step 4: Change the default for `raw` from `None` to `0.0`**

```python
def _add_entry(session, *, user_id, ticker, trade_date, rating,
               raw=0.0, status=MemoryEntryStatus.RESOLVED):
```

This is a one-character change (`None` → `0.0`). The signature stays otherwise identical. Existing callers all pass `raw=<float>` explicitly, so behavior is unchanged. The one caller using `raw=None, status=MemoryEntryStatus.PENDING` (around line 132-133) still works because the PENDING+None combination satisfies the invariant.

### 3c. Verify GREEN — no regressions anywhere

- [ ] **Step 5: Run the full default suite**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
```

Expected: still **136 passed**. The defensive branch removal does not affect any existing test because no test exercised that branch.

- [ ] **Step 6: Spot-check the dead branch is gone**

```bash
grep -n "if r is None" /Users/erikgunawansupriatna/TradingAgents/server/app/services/portfolio_calc.py
```

Expected: no output (empty). Confirms removal.

- [ ] **Step 7: Spot-check the test helper default**

```bash
grep -n "raw=None, status=MemoryEntryStatus.RESOLVED" /Users/erikgunawansupriatna/TradingAgents/server/tests/test_portfolio_router.py
```

Expected: no output (empty). The misleading default is gone.

- [ ] **Step 8: Lint pass**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/services/portfolio_calc.py tests/test_portfolio_router.py
```

Expected: `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/services/portfolio_calc.py server/tests/test_portfolio_router.py
git commit -m "$(cat <<'EOF'
refactor(server): remove dead defensive branch in _resolved_pnls

With the ck_memory_entry_resolved_has_raw_return constraint (Task 1)
and the sync_user demote (Task 2) in place, the
  if r is None: continue
guard in portfolio_calc._resolved_pnls is provably dead code. Removed.
Updated docstring to point at the constraint as the now-load-bearing
invariant. A future bug bypassing the constraint will surface loudly
as a TypeError on size*float(r) — desired behavior.

Also fixes test_portfolio_router._add_entry's misleading raw=None
default (no caller actually used it, but now-invariant-violating —
changed to raw=0.0).

Implements spec §7-8 of v3+ followup #2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Verification (final goal-backward check)

Before declaring done, an engineer (or `gsd-verifier` subagent) confirms each gate:

- [ ] **V1 — Full test suite green.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q 2>&1 | tail -3` shows **136 passed** (133 baseline + 3 new).
- [ ] **V2 — ORM-level invariant enforced.** Manually verify by reading `server/app/models/memory_entry.py`: `__table_args__` contains a `CheckConstraint(...)` with the SQL `status != 'RESOLVED' OR raw_return IS NOT NULL` and name `ck_memory_entry_resolved_has_raw_return`.
- [ ] **V3 — Migration file present and chained.** `cd /Users/erikgunawansupriatna/TradingAgents/server && DATABASE_URL=sqlite+aiosqlite:///:memory: uv run alembic heads` prints `b1c2d3e4f5a6 (head)`.
- [ ] **V4 — Migration backfill verified.** `tests/test_migration_resolved_check.py::test_migration_demotes_bad_rows_and_adds_constraint` passes.
- [ ] **V5 — sync_user demote path verified.** `tests/test_memory_mirror.py::test_sync_demotes_resolved_with_unparseable_raw` passes, including the WARNING log assertion.
- [ ] **V6 — Dead branch removed.** `grep -n "if r is None" server/app/services/portfolio_calc.py` returns empty.
- [ ] **V7 — Test helper default fixed.** `grep -n "raw=None, status=MemoryEntryStatus.RESOLVED" server/tests/test_portfolio_router.py` returns empty.
- [ ] **V8 — Zero caller / schema drift.** `git diff main..HEAD --name-only -- server/app/workers/tasks.py server/app/routers/portfolio.py server/app/schemas/portfolio.py` returns empty.
- [ ] **V9 — Ruff clean.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/models/memory_entry.py app/services/memory_mirror.py app/services/portfolio_calc.py alembic/versions/b1c2d3e4f5a6_memory_entry_resolved_check.py tests/test_models.py tests/test_memory_mirror.py tests/test_migration_resolved_check.py tests/test_portfolio_router.py` reports `All checks passed!`.
- [ ] **V10 — Spec sections covered:**
  - §3 invariant → Task 1 CheckConstraint
  - §4 enforcement → Task 1 model + migration
  - §5 alembic migration → Task 1c
  - §6 sync_user demote → Task 2
  - §7 dead-branch removal → Task 3a
  - §8 test helper cleanup → Task 3b
  - §9.1 ORM rejection test → Task 1a/1b
  - §9.2 demote test → Task 2b
  - §9.3 migration smoke test → Task 1d
  - §9.4 no extra test for _resolved_pnls → confirmed (intentionally skipped)

If V1-V10 all pass, the implementation is done.

---

## Out-of-scope reminders

These are deliberately NOT done by this plan (per spec §2):

- SQLAlchemy `@validates` ORM-layer validator (defense-in-depth — rejected).
- Pydantic discriminated union on `MemoryEntryOut` / `DecisionPin` (separate spec).
- v3+ followup #3 — `DecisionPin` cross-field invariant (separate followup).
- Coordination with v3+ #1 advisory lock (PR #4) — independent file scopes; either PR can land first.

If discovered during implementation, file as new followups — do not bundle.

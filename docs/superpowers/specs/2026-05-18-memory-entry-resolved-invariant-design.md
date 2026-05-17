# `MemoryEntry.status=RESOLVED` requires `raw_return` — Design

**Status:** Approved, awaiting implementation plan
**Date:** 2026-05-18
**Followup of:** PR #3 (Wave 3 — Portfolio P&L); v3+ followup #2 in the deferred list
**Independent of:** PR #4 (v3+ #1 advisory lock); branches off `main` directly
**Author:** erik

---

## 1. Problem

`MemoryEntry` permits a state that should be impossible: `status='RESOLVED'` with `raw_return IS NULL`. The row is representable in three places:

- **DB schema** — `raw_return: Mapped[float | None]` (`server/app/models/memory_entry.py:41`), `nullable=True` in the alembic migration `a1b2c3d4e5f6`.
- **ORM** — no SQLAlchemy validator rejects the combination.
- **Pydantic** — `MemoryEntryOut.raw_return: float | None` (`server/app/schemas/portfolio.py:13`) and `DecisionPin.raw_return: float | None` accept None unconditionally.

The bad state is created at exactly one site today: `memory_mirror.sync_user` (`server/app/services/memory_mirror.py:110-126`). The disk parser produces a non-pending entry (so we set `status=RESOLVED`); then `_pct_to_float` on a malformed `%` string returns `None` and we INSERT `(status=RESOLVED, raw_return=None)`.

The bad state is silently swallowed at the read site: `portfolio_calc._resolved_pnls` (`server/app/services/portfolio_calc.py:46-48`) has `if r is None: continue` — a defensive filter that masks the data error. No test exercises this branch; every existing `_add_entry(...)` call in `test_portfolio_router.py` passes an explicit `raw=` argument despite the helper's `raw=None, status=RESOLVED` defaults.

The v3+ list in PR #3's body called this out explicitly:

> `MemoryEntry.status=RESOLVED + raw_return=None` invariant enforcement — representable, silently skipped by `_resolved_pnls`

This spec eliminates both halves: the state becomes unrepresentable at the DB layer, the creation site cleanly demotes parse failures to PENDING, and the defensive read-side filter is removed so future violations fail loudly.

---

## 2. Goal & non-goals

**Goal.** Make `status=RESOLVED` rows with `raw_return IS NULL` impossible to persist. Convert the existing parse-failure path into a loud-but-recoverable demote-to-PENDING. Remove the now-dead defensive filter.

**Non-goals (deliberately).**

- **No SQLAlchemy `@validates` (ORM-layer validator).** A DB CHECK + the targeted `sync_user` change is sufficient. The validator would add a second enforcement layer at marginal cost; rejected as YAGNI per user choice ("full cleanup", not "defense-in-depth").
- **No Pydantic discriminated union on `MemoryEntryOut` / `DecisionPin`.** The output schemas carry both PENDING and RESOLVED entries, where PENDING legitimately has `raw_return=None`. A `(status='pending', raw_return: None) | (status='resolved', raw_return: float)` union would express it precisely but adds API surface complexity. Out of scope.
- **No v3+ followup #3 (`DecisionPin` cross-field invariant for `status='pending'` + non-null `raw_return`)** — its own followup.
- **No interaction with v3+ #1 advisory lock (PR #4).** The two PRs touch different files (`memory_mirror.py`'s lock primitives vs. `memory_entry.py`'s constraint + a few lines in `sync_user`). Independent branches; either can land first without rebase conflict.
- **No production data migration scenario.** The project has no production users; the migration's backfill is a future-readiness measure, not a live cleanup. If/when production data exists, the same backfill applies.

---

## 3. Invariant statement

For every row in `memory_entries`:

```
status = 'RESOLVED'  ⟹  raw_return IS NOT NULL
```

Equivalently: `status = 'PENDING' ∨ raw_return IS NOT NULL`. PENDING entries can still have `raw_return=None` (and almost always do — they're awaiting resolution).

---

## 4. Enforcement — DB CHECK constraint

### 4.1 Constraint definition

Added to `MemoryEntry.__table_args__` in `server/app/models/memory_entry.py`:

```python
from sqlalchemy import CheckConstraint

class MemoryEntry(Base):
    __tablename__ = "memory_entries"
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

Naming follows the existing project convention (`uq_<table_singular>_<cols>` → `ck_<table_singular>_<purpose>`).

### 4.2 Cross-dialect portability

Standard SQL `CHECK` works in both Postgres and SQLite. No dialect-gating required at the model layer.

### 4.3 Why `'RESOLVED'` (uppercase) in the SQL literal

The `MemoryEntryStatus` enum's column is `Enum(MemoryEntryStatus, name="memory_entry_status")`. SQLAlchemy serializes enum members by their **name** (`'PENDING'`, `'RESOLVED'`) for Postgres, but by their **value** (`'pending'`, `'resolved'`) on SQLite when stored as text. This is a real cross-dialect trap.

Resolution: the existing migration `a1b2c3d4e5f6` declared the Postgres enum as `sa.Enum('PENDING', 'RESOLVED', name='memory_entry_status')` — uppercase names match the Python enum member names. SQLite stores the same values (member names). So `'RESOLVED'` in the CHECK SQL is correct on both.

The implementation plan verifies this with a Postgres-backed integration test and an existing SQLite test.

---

## 5. Alembic migration

### 5.1 New migration: `<rev>_memory_entry_resolved_check.py`

`down_revision = 'a1b2c3d4e5f6'` (chains off the memory_entries table creation).

**Upgrade**:

```python
def upgrade() -> None:
    # Backfill: any existing RESOLVED row with NULL raw_return is by definition
    # a parse-failure that snuck through. Demote to PENDING so the new
    # constraint can be applied. Re-sync from disk recovers proper RESOLVED
    # status on next memory_mirror.sync_user run (with corrected disk data).
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
```

**Downgrade**:

```python
def downgrade() -> None:
    with op.batch_alter_table("memory_entries") as batch:
        batch.drop_constraint(
            "ck_memory_entry_resolved_has_raw_return", type_="check"
        )
    # No reverse backfill — once a row is demoted to PENDING in upgrade,
    # downgrade cannot infer the original raw_return value.
```

### 5.2 Why `batch_alter_table`

SQLite cannot `ALTER TABLE ADD CONSTRAINT`. `batch_alter_table` synthesizes a table-copy-and-rename. Postgres handles it natively (the batch is a no-op wrapper). Alembic's autogen for CHECK constraints on SQLite would otherwise silently produce a no-op migration.

### 5.3 Migration test

A new `test_alembic_migration_ck_resolved.py` (or extension of existing alembic tests, if any) runs the upgrade against a SQLite in-memory fixture pre-seeded with a `(RESOLVED, NULL)` row, then asserts:
- The row's status is now `PENDING`.
- Subsequent INSERT of `(RESOLVED, NULL)` raises `IntegrityError`.

---

## 6. `memory_mirror.sync_user` change

### 6.1 Demote-to-PENDING block

Modify `server/app/services/memory_mirror.py` inside the `for entry in parsed:` loop, immediately after computing `status` and `raw`:

```python
status = (
    MemoryEntryStatus.PENDING if entry.get("pending")
    else MemoryEntryStatus.RESOLVED
)
raw = _pct_to_float(entry.get("raw"))

# Spec §6: enforce the (RESOLVED ⟹ raw_return NOT NULL) invariant at the
# write boundary. If the disk says resolved but the raw value couldn't be
# parsed, demote to PENDING so the row is still useful (decision text,
# rating) and the user can fix the disk format on next sync.
if status is MemoryEntryStatus.RESOLVED and raw is None:
    logger.warning(
        "memory_mirror: demoting %s/%s to PENDING for user_id=%s — "
        "disk says resolved but raw_return is missing/malformed",
        ticker, trade_date, user_id,
    )
    status = MemoryEntryStatus.PENDING

alpha = _pct_to_float(entry.get("alpha"))
# ... rest unchanged ...
```

### 6.2 Why per-entry log (vs. aggregated count)

The existing `skipped` aggregated count logs `"skipped %d of %d entries (missing ticker/date/rating)"`. That's appropriate for entries dropped entirely. A demote is different: the row IS inserted, just with a corrected status. The operator probably wants the ticker+date to find the offending disk line. Per-entry WARNING is the right shape. If the disk file has many bad rows, log noise is acceptable cost for diagnosability.

### 6.3 No new failure mode

The demote path never raises. `sync_user`'s caller behavior is unchanged: processed count includes demoted rows (they were still successfully upserted). The function's return type and contract are preserved.

---

## 7. `portfolio_calc._resolved_pnls` cleanup

Remove the dead `if r is None: continue` guard. Lines 46-48 in `server/app/services/portfolio_calc.py`:

```python
# before
if e.get("status") != "resolved":
    continue
r = e.get("raw_return")
if r is None:
    continue
size = rating_to_size(e.get("rating"))

# after
if e.get("status") != "resolved":
    continue
r = e.get("raw_return")  # invariant: not None when status=='resolved'
size = rating_to_size(e.get("rating"))
```

The `.get()` call stays (dict-access safety against a missing key — a different concern from the value-null check). If `r` is ever None despite the invariant — i.e., a future bug bypasses the CHECK constraint — the subsequent `float(r)` will raise `TypeError: float() argument must be a string or a real number, not 'NoneType'`. **That's the desired loud-failure behavior**, not a regression.

### 7.1 Docstring update

The function's docstring currently says:

> Skips pending entries and entries with `raw_return=None`.

Updated to:

> Skips pending entries. Resolved entries always have `raw_return` set
> (enforced by `ck_memory_entry_resolved_has_raw_return` — spec §4.1).

---

## 8. Test helper cleanup

`server/tests/test_portfolio_router.py:32-49` — `_add_entry` has misleading defaults `raw=None, status=MemoryEntryStatus.RESOLVED` that, after the invariant is enforced, would IntegrityError if any caller actually used them. They're never used (verified — every call passes explicit `raw=`).

**Fix**: change the defaults to `raw=0.0, status=MemoryEntryStatus.RESOLVED`. This is a safe combination that satisfies the invariant and matches the "create a resolved entry" intent the helper is shaped around. Callers that want PENDING still pass `status=MemoryEntryStatus.PENDING, raw=None` explicitly (as the one current call at line 132-133 already does).

Alternative considered: make `raw` a required kwarg (no default). Rejected because it adds noise to the existing call sites that have specific `raw=` values anyway, and the helper's purpose is "default-to-resolved entry" — the default should be valid by construction.

---

## 9. New tests

### 9.1 `test_models.py::test_resolved_without_raw_return_rejected`

Insert a `MemoryEntry` with `status=RESOLVED, raw_return=None` via the ORM; flush; expect `IntegrityError`. Confirms the CHECK constraint is wired.

### 9.2 `test_memory_mirror.py::test_sync_demotes_resolved_with_unparseable_raw`

Write a disk fixture containing a non-pending entry whose raw column is `"n/a"` or `"BAD"` (parses to None). Run `sync_user`. Assert:
- The row was inserted with `status=PENDING`.
- A WARNING log was emitted containing the ticker, date, and "demoting … to PENDING".

### 9.3 Migration smoke test

Apply the new alembic migration against a SQLite in-memory DB pre-seeded with a `(status=RESOLVED, raw_return=NULL)` row. Assert:
- After upgrade: the row's status is `PENDING`.
- After upgrade: inserting a new `(RESOLVED, NULL)` row raises `IntegrityError`.
- Downgrade succeeds (constraint dropped, no exception).

### 9.4 No new test needed for `_resolved_pnls`

The existing happy-path tests still pass after the dead branch is removed. There's no need to test the "loud TypeError on None" path because the CHECK guarantees None can't reach the function; testing the failure mode would require monkey-patching past the constraint, which is exactly the kind of defensive test that re-creates the over-defensiveness we're removing.

---

## 10. Files touched

| File | Change |
|------|--------|
| `server/app/models/memory_entry.py` | Add `CheckConstraint` to `__table_args__`. |
| `server/alembic/versions/<rev>_memory_entry_resolved_check.py` | NEW migration (backfill demote + constraint). |
| `server/app/services/memory_mirror.py` | Add ~6-line demote-to-PENDING block. |
| `server/app/services/portfolio_calc.py` | Remove `if r is None: continue` + update docstring. |
| `server/tests/test_portfolio_router.py` | Change `_add_entry` defaults from `raw=None` to `raw=0.0`. |
| `server/tests/test_models.py` | NEW test for constraint enforcement. |
| `server/tests/test_memory_mirror.py` | NEW test for demote-on-parse-failure. |
| `server/tests/test_migration_resolved_check.py` (or similar) | NEW migration smoke test. |

No frontend changes. No Pydantic schema changes. No dependency changes. No diff to portfolio routers or worker — `sync_user`'s public contract is preserved (return type and value semantics unchanged).

---

## 11. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **The enum-value SQL literal disagreement.** If SQLAlchemy serializes the enum differently than the CHECK expects, the constraint either always-allows or always-rejects. | Cross-dialect test (SQLite + Postgres via testcontainers if available) verifies the CHECK catches a `(RESOLVED, NULL)` insert and permits `(PENDING, NULL)` + `(RESOLVED, 0.023)`. |
| **`batch_alter_table` on SQLite copies the table.** For very large tables this is slow. | Dev DB is small; non-issue today. Production would use Postgres which handles ALTER natively. |
| **Demote-to-PENDING masks the underlying disk bug.** The user might not notice their markdown is malformed if the log message is buried. | WARNING level + per-entry log with ticker/date is loud enough. Future enhancement (out of scope): emit a metric or surface in `/portfolio/summary` response. |
| **Migration downgrade is lossy.** Demoted rows stay PENDING even on rollback. | Documented explicitly in the migration. Downgrade is a development convenience, not a production-safety guarantee. |

---

## 12. Verification criteria

The implementation is done when all of the following are true:

1. `cd server && uv run pytest` — all 133 existing tests + new tests pass.
2. The new `test_resolved_without_raw_return_rejected` raises `IntegrityError` from a clean ORM INSERT attempt.
3. The new `test_sync_demotes_resolved_with_unparseable_raw` confirms the demote path + warning log.
4. The migration smoke test confirms backfill + constraint creation + downgrade succeed.
5. `grep -n "if r is None" server/app/services/portfolio_calc.py` returns nothing (dead branch removed).
6. `git diff main..HEAD -- server/app/workers/tasks.py server/app/routers/portfolio.py server/app/schemas/portfolio.py` is empty — no caller/schema drift.
7. Manual `git grep "raw=None, status=MemoryEntryStatus.RESOLVED"` finds zero matches (test helper defaults fixed).

---

## 13. References

- v3+ followup #2 in PR #3's body
- Wave 3 design spec §4.4 (memory_mirror)
- Existing migration: `server/alembic/versions/a1b2c3d4e5f6_add_memory_entries.py`
- SQLAlchemy CHECK constraints: https://docs.sqlalchemy.org/en/20/core/constraints.html#check-constraint
- Alembic `batch_alter_table` for SQLite: https://alembic.sqlalchemy.org/en/latest/batch.html

# `MemoryEntryStatusLiteral` Derive-From-Enum — Design

**Status:** Approved, awaiting implementation plan
**Date:** 2026-05-18
**Followup of:** PR #3 (Wave 3 — Portfolio P&L); v3+ followup #4 in the deferred list
**Conflicts (mechanical) with:** PR #6 (`feature/decision-pin-pending-invariant`) — both edit the same class bodies in `server/app/schemas/portfolio.py`. Whichever lands second needs a 3-line rebase.
**Independent of:** PR #4 (advisory lock) and PR #5 (RESOLVED-side invariant).
**Author:** erik

---

## 1. Problem

`server/app/schemas/portfolio.py:5` manually declares a `Literal` alias that duplicates the string values from `MemoryEntryStatus`:

```python
# schemas/portfolio.py
from typing import Literal
MemoryEntryStatusLiteral = Literal["pending", "resolved"]
```

The source of truth lives in `server/app/models/memory_entry.py`:

```python
class MemoryEntryStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
```

If a future change adds (e.g.) `IN_PROGRESS = "in_progress"` to the enum, the Pydantic alias does NOT update. Pydantic schemas would reject the new value at validation time, but the developer making the enum change has no compile-time signal that two-place editing is required.

The v3+ list captured the gap:

> `MemoryEntryStatusLiteral` derive-from-enum instead of duplicate string list

This spec eliminates the manual alias by typing the Pydantic fields directly with `MemoryEntryStatus`.

---

## 2. Goal & non-goals

**Goal.** Make `MemoryEntryStatus` the single source of truth for the (status) value set in both ORM and Pydantic. Adding a new status updates one place, not two.

**Non-goals (deliberately).**

- **No backward-compat alias.** `MemoryEntryStatusLiteral` is referenced only inside `server/app/schemas/portfolio.py` (verified by `grep -rn "MemoryEntryStatusLiteral" server/app server/tests web` — 3 matches, all in `portfolio.py`). No external consumer needs a transition path.
- **No shared-module extraction** of `MemoryEntryStatus` (e.g., into `app/shared/status.py`). Schemas importing from models is the conventional FastAPI pattern; adding an extra module for one importer is YAGNI.
- **No Pydantic config changes** (`use_enum_values=True` etc.). Defaults already produce the desired JSON output (lowercase string `.value`).
- **No TypeScript / OpenAPI-codegen update.** v3+ #12 (`openapi-typescript`) is its own followup; today there's no codegen and the wire format is unchanged.
- **No new tests required** (existing tests still pass), but **one small enum-input smoke test** is added as defensive coverage so a future Pydantic config regression that breaks enum-input would be caught.

---

## 3. Behavioral equivalence

The swap from `Literal["pending", "resolved"]` to `MemoryEntryStatus` is behaviorally equivalent for every flow that currently exists:

| Concern | `Literal` (today) | `MemoryEntryStatus` (after) | Notes |
|---------|-------------------|------------------------------|-------|
| Construction with string: `MemoryEntryOut(status="pending", ...)` | ✓ accepted | ✓ accepted | Pydantic v2 coerces string → enum member by `.value` matching. |
| Construction with enum: `MemoryEntryOut(status=MemoryEntryStatus.PENDING, ...)` | ✓ accepted | ✓ accepted | Already works on Literal too because str-enum members ARE strings. |
| Construction with invalid string: `MemoryEntryOut(status="foo", ...)` | ✗ ValidationError | ✗ ValidationError | Same outcome, slightly different error message. |
| Serialization: `MemoryEntryOut(...).model_dump()` | `{"status": "pending"}` | `{"status": "pending"}` | Default Pydantic v2 enum serialization uses `.value`. |
| Equality: `instance.status == "pending"` | True | True | Because `MemoryEntryStatus(str, enum.Enum)` — members ARE strings. PR #6's validators rely on this. |
| OpenAPI schema | inline `"enum": ["pending", "resolved"]` | `$ref` to a named `MemoryEntryStatus` component schema | Different shape but equivalent wire output. |

**No production code change is required outside `schemas/portfolio.py`.** No router, no service, no test (existing tests use string inputs which still work).

---

## 4. Implementation — single-file diff

`server/app/schemas/portfolio.py`:

```python
# before — relevant lines only
from typing import Literal

from pydantic import BaseModel, ConfigDict

MemoryEntryStatusLiteral = Literal["pending", "resolved"]


class MemoryEntryOut(BaseModel):
    ticker: str
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None
    ...


class DecisionPin(BaseModel):
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None
```

```python
# after
from pydantic import BaseModel, ConfigDict

from app.models.memory_entry import MemoryEntryStatus


class MemoryEntryOut(BaseModel):
    ticker: str
    trade_date: str
    rating: str
    status: MemoryEntryStatus
    raw_return: float | None
    ...


class DecisionPin(BaseModel):
    trade_date: str
    rating: str
    status: MemoryEntryStatus
    raw_return: float | None
```

Atomic edits:
1. Delete `from typing import Literal` (no other Literal usage in the file).
2. Add `from app.models.memory_entry import MemoryEntryStatus`.
3. Delete `MemoryEntryStatusLiteral = Literal["pending", "resolved"]`.
4. Replace `MemoryEntryStatusLiteral` with `MemoryEntryStatus` in `MemoryEntryOut.status`.
5. Replace `MemoryEntryStatusLiteral` with `MemoryEntryStatus` in `DecisionPin.status`.

---

## 5. New test (smoke coverage for enum input)

Append to `server/tests/test_schemas_portfolio.py`:

```python
def test_memory_entry_out_accepts_enum_input():
    """Both string ("pending") and MemoryEntryStatus enum member inputs
    must work after v3+ #4 swaps the field type. Guards against a future
    Pydantic config regression that breaks enum-typed field validation.
    """
    from app.models.memory_entry import MemoryEntryStatus

    e = MemoryEntryOut(
        ticker="NVDA", trade_date="2024-05-10", rating="Buy",
        status=MemoryEntryStatus.RESOLVED,
        raw_return=0.023, alpha_return=0.011, holding_days=7,
    )
    assert e.status == "resolved"  # str-enum equality
    assert e.status is MemoryEntryStatus.RESOLVED
```

Why this test, not more:
- The existing 5 tests in `test_schemas_portfolio.py` already cover string-input + happy/sad paths for both schemas.
- The single new test covers the path that's now possible (enum member as input) which existing tests don't exercise.
- A "test that invalid strings still reject" is unnecessary because Pydantic's built-in enum validation is already tested by Pydantic itself.

---

## 6. Files touched

| File | Change |
|------|--------|
| `server/app/schemas/portfolio.py` | 5 atomic edits per §4. |
| `server/tests/test_schemas_portfolio.py` | Append 1 smoke test per §5. |

No DB, no migration, no router, no service, no worker, no frontend, no alembic. Two files modified total.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **OpenAPI shape change breaks downstream consumers** | No active consumers depend on inline `enum` vs `$ref`. The web frontend's TypeScript types are hand-mirrored (v3+ #12 will replace with codegen). |
| **Pydantic v2 default enum serialization changes in a minor version** | Smoke test (`test_memory_entry_out_accepts_enum_input`) would fail loudly. Pinning would be the mitigation, but pydantic versioning is not in scope here. |
| **Conflict with PR #6 (`@model_validator` methods in same class bodies)** | Documented in PR body. Manual 3-line rebase by whoever lands second. |
| **Schemas → Models import edge** is new (today schemas/portfolio.py has zero `app.models` imports) | Conventional FastAPI pattern. If we ever want clean separation, move enum to `app/shared/` — that's a future spec, not this one. |

---

## 8. Verification criteria

The implementation is done when all of the following are true:

1. `cd server && uv run pytest -q` — all existing tests + 1 new test pass.
2. `grep -n "MemoryEntryStatusLiteral" server/app server/tests` returns empty (alias fully removed).
3. `grep -n "from typing import Literal" server/app/schemas/portfolio.py` returns empty.
4. `grep -n "from app.models.memory_entry import" server/app/schemas/portfolio.py` returns 1 match.
5. `cd server && uv run ruff check app/schemas/portfolio.py tests/test_schemas_portfolio.py` reports clean.
6. `cd server && uv run python -c "from app.schemas.portfolio import MemoryEntryOut; from app.models.memory_entry import MemoryEntryStatus; print(MemoryEntryOut(ticker='X', trade_date='2024-05-10', rating='Buy', status=MemoryEntryStatus.RESOLVED, raw_return=0.02, alpha_return=None, holding_days=None).model_dump())"` outputs `{'ticker': 'X', 'trade_date': '2024-05-10', 'rating': 'Buy', 'status': 'resolved', 'raw_return': 0.02, 'alpha_return': None, 'holding_days': None}` (or equivalent dict) — confirms serialization still produces lowercase string.
7. `git diff main..HEAD --name-only -- server/app/models server/alembic server/app/services server/app/workers server/app/routers web/` returns empty (zero out-of-scope drift).

---

## 9. References

- v3+ followup #4 in PR #3's body
- Pydantic v2 enum field docs: https://docs.pydantic.dev/latest/api/standard_library_types/#enum
- `MemoryEntryStatus`: `server/app/models/memory_entry.py:20-23`
- Current alias: `server/app/schemas/portfolio.py:5`

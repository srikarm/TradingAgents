# `MemoryEntryStatusLiteral` Derive-From-Enum — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `MemoryEntryStatusLiteral = Literal["pending", "resolved"]` in `server/app/schemas/portfolio.py` with direct use of the `MemoryEntryStatus` enum from `server/app/models/memory_entry.py`. Closes v3+ followup #4.

**Architecture:** Single-file refactor. The Pydantic schemas already accept strings at construction time (because `MemoryEntryStatus(str, enum.Enum)`); the change is purely a type-annotation swap. One small smoke test verifies enum-input also works. Zero behavioral change for valid inputs; the wire format (JSON) is unchanged.

**Tech Stack:** Python 3.10+, Pydantic v2, SQLAlchemy 2.0 enum columns.

**Spec:** `docs/superpowers/specs/2026-05-18-status-literal-from-enum-design.md`

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `server/app/schemas/portfolio.py` | MODIFY | Drop `Literal` import + `MemoryEntryStatusLiteral` alias; add `MemoryEntryStatus` import; swap 2 field type annotations. |
| `server/tests/test_schemas_portfolio.py` | MODIFY | Append 1 smoke test asserting enum-input also works. |

No DB, no migration, no router, no service, no worker, no frontend, no alembic. Two files modified.

---

## Task 1: Swap `MemoryEntryStatusLiteral` for `MemoryEntryStatus` + smoke test

One atomic commit. TDD-ordered internally: write the enum-input smoke test first (will pass on existing schema because str-enum members are accepted), do the swap, re-verify.

**Files:**
- Modify: `server/app/schemas/portfolio.py`
- Modify: `server/tests/test_schemas_portfolio.py`

### 1a. Confirm pre-state (baseline)

- [ ] **Step 1: Confirm `MemoryEntryStatusLiteral` is only used in `schemas/portfolio.py`**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && grep -rn "MemoryEntryStatusLiteral" server/app server/tests web 2>/dev/null | grep -v ".pyc\|node_modules\|.next"
```

Expected output (3 matches, all in `schemas/portfolio.py`):

```
server/app/schemas/portfolio.py:5:MemoryEntryStatusLiteral = Literal["pending", "resolved"]
server/app/schemas/portfolio.py:12:    status: MemoryEntryStatusLiteral
server/app/schemas/portfolio.py:47:    status: MemoryEntryStatusLiteral
```

If any other file references the alias, STOP — this plan assumed no external consumers; investigate before continuing.

- [ ] **Step 2: Confirm `Literal` is only used by the alias line**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && grep -n "Literal" server/app/schemas/portfolio.py
```

Expected: 2 matches (the `from typing import Literal` import and the `MemoryEntryStatusLiteral = Literal[...]` line). If there are more, the `from typing import Literal` removal would break the file — leave the import alone.

### 1b. Write the enum-input smoke test

- [ ] **Step 3: Open `server/tests/test_schemas_portfolio.py`** to confirm structure.

The file currently imports `pytest` and from `app.schemas.portfolio` imports the various BaseModel classes. New imports should be appended cleanly.

- [ ] **Step 4: Append the smoke test to `server/tests/test_schemas_portfolio.py`**

Add this test at the end of the file (do not duplicate existing imports — `MemoryEntryOut` is already imported; `MemoryEntryStatus` is new):

```python
from app.models.memory_entry import MemoryEntryStatus


def test_memory_entry_out_accepts_enum_input():
    """Both string ("pending") and MemoryEntryStatus enum member inputs
    must work after v3+ #4 swaps the field type. Guards against a future
    Pydantic config regression that breaks enum-typed field validation.
    """
    e = MemoryEntryOut(
        ticker="NVDA",
        trade_date="2024-05-10",
        rating="Buy",
        status=MemoryEntryStatus.RESOLVED,
        raw_return=0.023,
        alpha_return=0.011,
        holding_days=7,
    )
    assert e.status == "resolved"  # str-enum equality
    assert e.status is MemoryEntryStatus.RESOLVED
```

- [ ] **Step 5: Run the smoke test — verify it passes against the current schema**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py::test_memory_entry_out_accepts_enum_input -v
```

Expected: `PASSED`. The test passes against the `Literal["pending", "resolved"]` field type because `MemoryEntryStatus.RESOLVED` is a `str` instance equal to `"resolved"` and Pydantic accepts it. This is the **baseline behavior** the refactor must preserve.

If this test fails BEFORE the refactor, something about the current schema is unexpected — STOP and investigate before swapping types.

### 1c. Apply the type-annotation swap

- [ ] **Step 6: Modify `server/app/schemas/portfolio.py`** — update imports.

Current first 5 lines:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict

MemoryEntryStatusLiteral = Literal["pending", "resolved"]
```

Replace with:

```python
from pydantic import BaseModel, ConfigDict

from app.models.memory_entry import MemoryEntryStatus
```

(Removes the `from typing import Literal` line, removes the alias line, adds the model import. The blank line between import groups stays.)

- [ ] **Step 7: Modify `MemoryEntryOut.status` field annotation**

Find this line in the `MemoryEntryOut` class (currently around line 12):

```python
    status: MemoryEntryStatusLiteral
```

Replace with:

```python
    status: MemoryEntryStatus
```

- [ ] **Step 8: Modify `DecisionPin.status` field annotation**

Find this line in the `DecisionPin` class (currently around line 47):

```python
    status: MemoryEntryStatusLiteral
```

Replace with:

```python
    status: MemoryEntryStatus
```

### 1d. Verify GREEN

- [ ] **Step 9: Run the smoke test — verify it still passes after the swap**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py::test_memory_entry_out_accepts_enum_input -v
```

Expected: `PASSED`. Same as Step 5 — behavior is preserved.

- [ ] **Step 10: Run all schema tests — verify no regression**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py -v
```

Expected: all schema tests pass (5 pre-existing + 1 new = 6 passed). The pre-existing tests use `status="pending"` / `status="resolved"` string inputs which still work with the enum-typed field.

- [ ] **Step 11: Run the full default suite — verify no broader regression**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
```

Expected: 133 baseline + 1 new = **134 passed**. The router code that constructs `DecisionPin(... status=r.status.value)` (where `r.status` is the ORM enum) still works because `r.status.value` is the string `"pending"` / `"resolved"`, which the enum-typed field accepts.

- [ ] **Step 12: Verify serialization is unchanged**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run python -c "
from app.schemas.portfolio import MemoryEntryOut
from app.models.memory_entry import MemoryEntryStatus
m = MemoryEntryOut(
    ticker='X', trade_date='2024-05-10', rating='Buy',
    status=MemoryEntryStatus.RESOLVED,
    raw_return=0.02, alpha_return=None, holding_days=None,
)
print(m.model_dump())
print(m.model_dump_json())
"
```

Expected output (or equivalent dict ordering):

```
{'ticker': 'X', 'trade_date': '2024-05-10', 'rating': 'Buy', 'status': <MemoryEntryStatus.RESOLVED: 'resolved'>, 'raw_return': 0.02, 'alpha_return': None, 'holding_days': None}
{"ticker":"X","trade_date":"2024-05-10","rating":"Buy","status":"resolved","raw_return":0.02,"alpha_return":null,"holding_days":null}
```

Notes:
- `model_dump()` keeps the enum member in dict form (Python-level).
- `model_dump_json()` serializes to the string value `"resolved"` (lowercase) on the wire.

If the JSON output shows `"RESOLVED"` (uppercase name) or `"MemoryEntryStatus.RESOLVED"`, the Pydantic enum serialization is not producing the expected `.value` form — STOP and investigate `model_config` (you may need `use_enum_values=True`, but per the spec the default should work).

- [ ] **Step 13: Verify the alias is gone and the import is added**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && grep -n "MemoryEntryStatusLiteral\|from typing import Literal" server/app/schemas/portfolio.py
```

Expected: no output (empty). Both the alias and the now-unused `Literal` import are gone.

```bash
cd /Users/erikgunawansupriatna/TradingAgents && grep -n "from app.models.memory_entry import MemoryEntryStatus" server/app/schemas/portfolio.py
```

Expected: 1 match.

- [ ] **Step 14: Lint pass**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/schemas/portfolio.py tests/test_schemas_portfolio.py
```

Expected: `All checks passed!`. (Special attention: ruff should not flag the new `from app.models.memory_entry import MemoryEntryStatus` import as unused — it's used as a type annotation, which ruff understands.)

- [ ] **Step 15: Verify zero out-of-scope drift**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && git diff main..HEAD --name-only -- server/app/models server/alembic server/app/services server/app/workers server/app/routers web/
```

Expected: empty output. Only schemas + tests should be modified.

- [ ] **Step 16: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/schemas/portfolio.py server/tests/test_schemas_portfolio.py
git commit -m "$(cat <<'EOF'
refactor(server): derive status field type from MemoryEntryStatus enum

Replaces the manually-maintained `MemoryEntryStatusLiteral = Literal[
"pending", "resolved"]` alias in `server/app/schemas/portfolio.py`
with direct use of the `MemoryEntryStatus` enum from
`server/app/models/memory_entry.py`. Adding a new status now updates
one place, not two.

Behaviorally equivalent for all currently-exercised flows:
- String input ("pending") still accepted (Pydantic coerces).
- Enum input (MemoryEntryStatus.RESOLVED) still accepted.
- Wire output unchanged (JSON serializes enum .value, lowercase).
- str-enum equality preserved (PR #6's `self.status == "pending"`
  validator still works).

New smoke test asserts enum-input acceptance to guard against a
future Pydantic config regression.

Implements v3+ followup #4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Verification (final goal-backward check)

Before declaring done, an engineer (or `gsd-verifier` subagent) confirms each gate:

- [ ] **V1 — Full suite green.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q 2>&1 | tail -3` shows **134 passed** (133 baseline + 1 new).
- [ ] **V2 — Alias and Literal import gone.** `grep -n "MemoryEntryStatusLiteral\|from typing import Literal" server/app/schemas/portfolio.py` returns empty.
- [ ] **V3 — Enum import present.** `grep -n "from app.models.memory_entry import MemoryEntryStatus" server/app/schemas/portfolio.py` returns 1 match.
- [ ] **V4 — Field annotations use the enum.** `grep -n "status:" server/app/schemas/portfolio.py` returns 2 matches, both `status: MemoryEntryStatus`.
- [ ] **V5 — Wire serialization unchanged.** Step 12's JSON output contains `"status":"resolved"` (lowercase string).
- [ ] **V6 — Smoke test passes.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py::test_memory_entry_out_accepts_enum_input -v` shows 1 passed.
- [ ] **V7 — Pre-existing tests still pass.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py -v` shows 6 passed.
- [ ] **V8 — Zero out-of-scope drift.** `git diff main..HEAD --name-only` lists exactly the spec, plan, and 2 modified files.
- [ ] **V9 — Ruff clean.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/schemas/portfolio.py tests/test_schemas_portfolio.py 2>&1 | tail -3` reports `All checks passed!`.
- [ ] **V10 — Spec sections covered:**
  - §3 behavioral-equivalence table → V1, V5, V6, V7
  - §4 5 atomic edits → Steps 6-8
  - §5 smoke test → Step 4
  - §6 files touched → matches V8
  - §8 verification criteria → mirrors V1-V9

If V1-V10 all pass, the implementation is done.

---

## Out-of-scope reminders

These are deliberately NOT done by this plan (per spec §2):

- Backward-compat alias `MemoryEntryStatusLiteral = MemoryEntryStatus` (no external consumers).
- Shared-module extraction of `MemoryEntryStatus` to `app/shared/`.
- Pydantic config changes (`use_enum_values=True` etc.).
- TypeScript / openapi-typescript codegen update (v3+ #12).
- Any change outside `server/app/schemas/portfolio.py` and `server/tests/test_schemas_portfolio.py`.

If discovered during implementation, file as new followups — do not bundle.

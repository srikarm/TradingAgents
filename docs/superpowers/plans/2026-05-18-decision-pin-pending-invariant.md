# `DecisionPin` & `MemoryEntryOut` Pending-Implies-Null-Raw Invariant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject `(status="pending", raw_return is not None)` at the Pydantic schema layer for `DecisionPin` and `MemoryEntryOut`. Closes v3+ followup #3.

**Architecture:** Add an identical `@model_validator(mode='after')` to both schemas. No DB change, no migration, no router code change. Three new schema-level tests (two rejection paths + one explicit happy-path) plus one router-level integration test ensure (a) the validator fires correctly, (b) the existing happy paths still construct, and (c) a real PENDING row flows through `/portfolio/ticker/{ticker}` end-to-end without tripping the validator.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest-asyncio, FastAPI.

**Spec:** `docs/superpowers/specs/2026-05-18-decision-pin-pending-invariant-design.md`

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `server/app/schemas/portfolio.py` | MODIFY | Add `model_validator` to pydantic import; add `@model_validator(mode='after')` to `DecisionPin` and `MemoryEntryOut`. |
| `server/tests/test_schemas_portfolio.py` | MODIFY | Add 3 new tests: DecisionPin reject, DecisionPin accept-pending-null, MemoryEntryOut reject. Existing tests stay. |
| `server/tests/test_portfolio_router.py` | MODIFY | Add 1 integration test: a PENDING entry round-trips through `/portfolio/ticker/{ticker}` without 500. |

No DB, no migration, no models, no services, no routers, no frontend. Three files modified total.

---

## Task 1: Add validators + 4 new tests + verify GREEN

This task is one atomic commit. TDD-ordered internally: failing schema tests → schema validators → integration test → final verification.

**Files:**
- Modify: `server/app/schemas/portfolio.py`
- Modify: `server/tests/test_schemas_portfolio.py`
- Modify: `server/tests/test_portfolio_router.py`

### 1a. Write the failing schema tests (RED)

- [ ] **Step 1: Open `server/tests/test_schemas_portfolio.py`** to confirm import structure.

The file currently imports `from app.schemas.portfolio import (DecisionPin, MemoryEntryOut, PnLPoint, PortfolioCurveOut, PortfolioSummaryOut, PricePoint, TickerDetailOut)`.

- [ ] **Step 2: Append 3 new tests + the `ValidationError` import to `server/tests/test_schemas_portfolio.py`**

Add `ValidationError` to the existing pydantic-related imports (or as a new import line). The existing top imports `pytest` already; if `from pydantic import ValidationError` is not already present, add it.

Append at the end of the file:

```python
from pydantic import ValidationError


def test_decision_pin_rejects_pending_with_raw_return():
    """Spec §3: status='pending' requires raw_return=None."""
    with pytest.raises(ValidationError):
        DecisionPin(
            trade_date="2024-05-10",
            rating="Buy",
            status="pending",
            raw_return=0.5,
        )


def test_decision_pin_accepts_pending_with_null_raw():
    """The valid pending case (status='pending', raw_return=None) must pass."""
    pin = DecisionPin(
        trade_date="2024-05-10",
        rating="Buy",
        status="pending",
        raw_return=None,
    )
    assert pin.status == "pending"
    assert pin.raw_return is None


def test_memory_entry_out_rejects_pending_with_raw_return():
    """Spec §3 mirrored on MemoryEntryOut."""
    with pytest.raises(ValidationError):
        MemoryEntryOut(
            ticker="NVDA",
            trade_date="2024-05-10",
            rating="Buy",
            status="pending",
            raw_return=0.5,
            alpha_return=None,
            holding_days=None,
        )
```

- [ ] **Step 3: Run schema tests — verify RED**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py -v
```

Expected: the two `rejects_pending_with_raw_return` tests **FAIL** (because no validator exists yet, construction succeeds and `pytest.raises(ValidationError)` finds no exception). The `accepts_pending_with_null_raw` test **PASSES** (it's a valid construction).

If both reject tests fail with `DID NOT RAISE` and the accept test passes, the RED phase is correctly signaling the gap. Move on.

### 1b. Add the validators (GREEN — part 1)

- [ ] **Step 4: Modify `server/app/schemas/portfolio.py`** — update imports.

Find the current pydantic import:

```python
from pydantic import BaseModel, ConfigDict
```

Replace with:

```python
from pydantic import BaseModel, ConfigDict, model_validator
```

- [ ] **Step 5: Add the `@model_validator` to `MemoryEntryOut`**

The current class:

```python
class MemoryEntryOut(BaseModel):
    ticker: str
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None
    alpha_return: float | None
    holding_days: int | None

    model_config = ConfigDict(from_attributes=True)
```

Replace with (add the new method after `model_config`):

```python
class MemoryEntryOut(BaseModel):
    ticker: str
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None
    alpha_return: float | None
    holding_days: int | None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _pending_requires_null_raw(self) -> "MemoryEntryOut":
        if self.status == "pending" and self.raw_return is not None:
            raise ValueError(
                f"MemoryEntryOut invariant violated: status='pending' requires "
                f"raw_return=None, got {self.raw_return!r}"
            )
        return self
```

- [ ] **Step 6: Add the `@model_validator` to `DecisionPin`**

The current class:

```python
class DecisionPin(BaseModel):
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None
```

Replace with:

```python
class DecisionPin(BaseModel):
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None

    @model_validator(mode="after")
    def _pending_requires_null_raw(self) -> "DecisionPin":
        if self.status == "pending" and self.raw_return is not None:
            raise ValueError(
                f"DecisionPin invariant violated: status='pending' requires "
                f"raw_return=None, got {self.raw_return!r}"
            )
        return self
```

The duplication between the two `_pending_requires_null_raw` methods is intentional — see spec §4.2.

- [ ] **Step 7: Run schema tests — verify GREEN**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py -v
```

Expected: all schema tests pass (including the 3 new ones and the existing `test_memory_entry_out_accepts_resolved` and `test_memory_entry_out_accepts_pending_with_nulls`).

### 1c. Add the router integration test

- [ ] **Step 8: Open `server/tests/test_portfolio_router.py`** to confirm helper + imports.

The file imports `MemoryEntry`, `MemoryEntryStatus`, `User`, `make_jwt`, and the `client`/`db_session` fixtures. It defines a `_add_entry` helper around line 32-49 that constructs a MemoryEntry. Also imports `portfolio_router` and `_pc` (price_cache) lower in the file (around line 145-146) for tests that need to patch the price-fetch function.

- [ ] **Step 9: Append the integration test to `server/tests/test_portfolio_router.py`**

Add this test at the end of the file:

```python
@pytest.mark.asyncio
async def test_ticker_detail_renders_pending_entry(
    client, db_session, monkeypatch,
):
    """A PENDING entry (raw_return=None) must round-trip through
    /portfolio/ticker/{ticker} without tripping the DecisionPin
    pending-implies-null-raw validator (spec §5.2 — the validator
    must not 500 on legitimate pending data)."""
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-tpend"))
    _add_entry(
        db_session, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
        rating="Buy", raw=None, status=MemoryEntryStatus.PENDING,
    )
    await db_session.flush()

    async def fake_fetch(dashboard_dir, *, user_id, ticker, start, end):
        return [{"trade_date": "2024-05-10", "close": 100.0}]
    monkeypatch.setattr(portfolio_router, "_fetch_prices", fake_fetch)

    async with client as c:
        r = await c.get(
            "/portfolio/ticker/NVDA",
            headers={"Authorization": f"Bearer {make_jwt('gh-tpend')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body["decisions"]) == 1
    assert body["decisions"][0]["status"] == "pending"
    assert body["decisions"][0]["raw_return"] is None
```

(`portfolio_router` is already imported lower in the file at line 145 — `from app.routers import portfolio as portfolio_router  # noqa: E402`. Use that existing import; don't re-import at the top.)

- [ ] **Step 10: Run the integration test — verify GREEN**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_portfolio_router.py::test_ticker_detail_renders_pending_entry -v
```

Expected: `1 passed`. The PENDING entry's `raw_return=None` is valid per the new validator, so the endpoint returns 200 with one decision pin.

### 1d. Final verification

- [ ] **Step 11: Run the full default suite**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
```

Expected: all existing 133 baseline tests + 4 new tests = **137 passed**.

- [ ] **Step 12: Verify zero drift to out-of-scope files**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && git diff main..HEAD --name-only
```

Expected output (4 files):

```
docs/superpowers/specs/2026-05-18-decision-pin-pending-invariant-design.md
server/app/schemas/portfolio.py
server/tests/test_portfolio_router.py
server/tests/test_schemas_portfolio.py
```

If any other file appears (models, alembic, routers/portfolio.py, services, web/, etc.), the implementation drifted from the spec — investigate.

- [ ] **Step 13: Lint pass**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/schemas/portfolio.py tests/test_schemas_portfolio.py tests/test_portfolio_router.py
```

Expected: `All checks passed!`.

- [ ] **Step 14: Commit**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git add server/app/schemas/portfolio.py \
        server/tests/test_schemas_portfolio.py \
        server/tests/test_portfolio_router.py
git commit -m "$(cat <<'EOF'
feat(server): DecisionPin invariant — pending ⟹ raw_return is None

Adds @model_validator(mode='after') to DecisionPin and MemoryEntryOut
rejecting (status='pending', raw_return is not None). Closes v3+ #3.

Together with PR #5's DB CHECK constraint on the RESOLVED side, the
two PRs form a complete tagged union:
  status='resolved'  ⟺  raw_return IS NOT NULL
  status='pending'   ⟺  raw_return IS None

Pydantic-only enforcement (no DB change) — see spec §6 for the
rationale. Tests cover both rejection paths, the happy-path pending
case, and an end-to-end /portfolio/ticker/{ticker} round-trip with a
PENDING entry to guarantee the validator doesn't 500 on legitimate
data.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Verification (final goal-backward check)

Before declaring done, an engineer (or `gsd-verifier` subagent) confirms each gate:

- [ ] **V1 — Full suite green.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q 2>&1 | tail -3` shows **137 passed**.
- [ ] **V2 — Both rejection tests fire.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py::test_decision_pin_rejects_pending_with_raw_return tests/test_schemas_portfolio.py::test_memory_entry_out_rejects_pending_with_raw_return -v 2>&1 | tail -3` shows 2 passed.
- [ ] **V3 — Integration test fires.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_portfolio_router.py::test_ticker_detail_renders_pending_entry -v 2>&1 | tail -3` shows 1 passed.
- [ ] **V4 — Validators present.** `grep -n "_pending_requires_null_raw" /Users/erikgunawansupriatna/TradingAgents/server/app/schemas/portfolio.py` returns 2 matches.
- [ ] **V5 — Existing happy-path tests still pass.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest tests/test_schemas_portfolio.py::test_memory_entry_out_accepts_pending_with_nulls tests/test_schemas_portfolio.py::test_memory_entry_out_accepts_resolved -v 2>&1 | tail -3` shows 2 passed.
- [ ] **V6 — Zero drift to out-of-scope files.** `git diff main..HEAD --name-only` lists exactly: spec doc + 3 modified files (`schemas/portfolio.py`, `test_schemas_portfolio.py`, `test_portfolio_router.py`). No models, no alembic, no routers code, no services, no web/.
- [ ] **V7 — Ruff clean.** `cd /Users/erikgunawansupriatna/TradingAgents/server && uv run ruff check app/schemas/portfolio.py tests/test_schemas_portfolio.py tests/test_portfolio_router.py 2>&1 | tail -3` reports `All checks passed!`.
- [ ] **V8 — Spec sections covered:**
  - §3 invariant → Steps 5-6 (the two validators)
  - §4 enforcement → Steps 4-6
  - §5 behavior on violation → Steps 2 and 9 (tests use `ValidationError`, integration test confirms 200 on valid pending)
  - §7.1 schema tests → Step 2
  - §7.2 integration test → Step 9
  - §7.3 no-500-path-test rationale → not implemented, by design
  - §8 files touched → matches Steps 4-9
  - §10 verification → V1-V7

If V1-V8 all pass, the implementation is done.

---

## Out-of-scope reminders

These are deliberately NOT done by this plan (per spec §2):

- DB CHECK constraint (avoids PR #5 migration-chain conflict).
- Pydantic discriminated union (changes OpenAPI shape + breaks TypeScript interface).
- SQLAlchemy ORM validator on `MemoryEntry.raw_return`.
- Removal of unused `MemoryEntryOut` schema (v3+ #4 territory).
- Frontend TypeScript change (already accepts `null`).

If discovered during implementation, file as new followups — do not bundle.

# `DecisionPin` & `MemoryEntryOut` Pending-Implies-Null-Raw Invariant — Design

**Status:** Approved, awaiting implementation plan
**Date:** 2026-05-18
**Followup of:** PR #3 (Wave 3 — Portfolio P&L); v3+ followup #3 in the deferred list
**Independent of:** PR #4 (advisory lock) and PR #5 (RESOLVED-side invariant); branches off `main` directly
**Author:** erik

---

## 1. Problem

Two Pydantic schemas — `DecisionPin` (used by `/portfolio/ticker/{ticker}`) and `MemoryEntryOut` (defined but currently unused by any router) — both type `status: MemoryEntryStatusLiteral` and `raw_return: float | None` with no cross-field validation. They silently accept the logically-impossible state `(status="pending", raw_return: float)`.

For pending decisions, the prediction window hasn't elapsed yet, so a realized return cannot exist. The state is incoherent: "I haven't measured this yet, but here's the measurement."

### Where the bad state could come from (today)
- **Disk parser** (`tradingagents/agents/utils/memory.py`): pending entries have the disk-tag form `[date | ticker | rating | pending]` — 4 fields, no raw column. `entry.get("raw")` returns `None`. `memory_mirror.sync_user` always produces `(PENDING, None)` for these. **Production-safe.**
- **`memory_mirror.sync_user`**: same as above — never produces the bad state. **Production-safe.**
- **Direct ORM construction** (e.g., a new endpoint, a manual SQL test, a future feature): not blocked. **Risk surface.**
- **Tests** (`test_portfolio_router._add_entry`): one call constructs `(PENDING, None)` — valid. None construct the bad state today.

The v3+ list captured the gap:

> `DecisionPin` cross-field invariant (`status="pending"` + non-null raw_return)

This spec closes the gap at the Pydantic schema layer, mirroring v3+ #2's contribution on the resolved side. Together with #2's DB CHECK, the two form a complete tagged union:

```
status='resolved'  ⟺  raw_return IS NOT NULL
status='pending'   ⟺  raw_return IS None
```

---

## 2. Goal & non-goals

**Goal.** Make `DecisionPin` and `MemoryEntryOut` reject instantiation when `status="pending"` and `raw_return is not None`. Document the invariant in code via a Pydantic `@model_validator(mode='after')`. Add tests confirming both the reject path and the still-valid happy paths.

**Non-goals (deliberately).**

- **No DB CHECK constraint for the pending side.** Adding one would touch `server/app/models/memory_entry.py.__table_args__` and create a new alembic migration — both of which PR #5 (v3+ #2) is also doing. The migration-chain merge friction is not worth the marginal defense-in-depth, especially given the production path never creates this state. Spec §6 explains the choice.
- **No Pydantic discriminated union** (`Annotated[Union[PendingDecisionPin, ResolvedDecisionPin], Field(discriminator="status")]`). It would express the invariant at the type level but changes the OpenAPI schema (two variants), breaks the simple `web/lib/types.ts` `DecisionPin` interface, and forces a frontend update. Cost > benefit at current scale.
- **No SQLAlchemy ORM validator** on `MemoryEntry.raw_return`. The DB layer's enforcement is PR #5's territory; doubling it up at the ORM layer with no DB change here would create inconsistent enforcement.
- **No removal of the currently-unused `MemoryEntryOut` schema.** It's listed in v3+ #4 for a separate `MemoryEntryStatusLiteral` derive-from-enum cleanup; touching it for removal here would scope-creep.
- **No frontend type change.** TypeScript already accepts `null` on `raw_return`; the Pydantic enforcement is invisible to the wire format on valid responses.

---

## 3. Invariant statement

For any instance of `DecisionPin` or `MemoryEntryOut`:

```
status == "pending"  ⟹  raw_return IS None
```

Equivalent SQL-like form: `status != "pending" OR raw_return IS None`.

Combined with PR #5's DB constraint `ck_memory_entry_resolved_has_raw_return` (`status != 'RESOLVED' OR raw_return IS NOT NULL`), the two yield the tagged-union contract: status discriminates exactly which states `raw_return` can be in.

---

## 4. Enforcement — Pydantic `@model_validator(mode='after')`

### 4.1 Schema modification

In `server/app/schemas/portfolio.py`, add `model_validator` to the pydantic import, then add an identical `@model_validator(mode='after')` method to both `DecisionPin` and `MemoryEntryOut`:

```python
from pydantic import BaseModel, ConfigDict, model_validator


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


# ... PnLPoint, PortfolioSummaryOut, PortfolioCurveOut, PricePoint unchanged ...


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

### 4.2 Why duplicate the validator instead of extracting

Two short identical methods, two short identical error messages — the only difference is the class name in the message. A mixin (e.g., `class _PendingRawValidator: ...`) or a module-level helper would save ~6 lines but introduce indirection (the reader has to chase the helper to confirm what's enforced). With exactly two callers and a future where a third callout would be unusual (other schemas don't share the `(status, raw_return)` shape), inline is the right balance. If a fourth schema ever needs it, extract then.

### 4.3 Validator placement (mode='after')

`mode='after'` runs after field validation, so `self.status` and `self.raw_return` are guaranteed to be typed correctly when the check runs. `mode='before'` would receive raw input dicts and require more defensive code.

---

## 5. Behavior on violation

`@model_validator(mode='after')` raising `ValueError` is wrapped by Pydantic into `ValidationError` at construction time. Two consequences:

### 5.1 Test usage
Tests that construct violating instances must use `pytest.raises(ValidationError)` (not `ValueError`):

```python
from pydantic import ValidationError

with pytest.raises(ValidationError):
    DecisionPin(trade_date="2024-05-10", rating="Buy",
                status="pending", raw_return=0.5)
```

### 5.2 Router usage
`server/app/routers/portfolio.py:138-145` constructs `DecisionPin` from DB rows inside the `/portfolio/ticker/{ticker}` handler. If a violation occurs at construction time:

- Pydantic raises `ValidationError` from the constructor.
- The handler does not catch it.
- FastAPI's default exception handling turns it into a **500 Internal Server Error**.

**This is the right behavior.** The production data path (disk parser → `sync_user`) cannot produce a violating MemoryEntry, so the validator never fires in practice. If it ever does fire, something genuinely unexpected has happened (direct SQL INSERT, future endpoint bypassing the parser, a parser regression). A 500 surfaces the bug fast; silently sanitizing (e.g., setting `raw_return=None`) would hide it.

**UX risk assessment**: zero today. The bad state cannot be produced by current code, so the endpoint cannot 500 on a real user's data because of this validator.

---

## 6. Why no DB CHECK constraint here

PR #5 (v3+ #2) adds `ck_memory_entry_resolved_has_raw_return` to `memory_entries` via a CheckConstraint in `MemoryEntry.__table_args__` plus a new alembic migration `b1c2d3e4f5a6_memory_entry_resolved_check.py`. Adding a mirror `ck_memory_entry_pending_has_null_raw` from this branch would:

1. **Conflict on `__table_args__`**: both branches would add a new `CheckConstraint(...)` to the tuple. Git can usually auto-merge tuple additions, but a clean rebase by hand is safer.
2. **Conflict on the alembic chain**: both branches create new migrations chaining off `down_revision = "a1b2c3d4e5f6"`. After merging both, alembic would see two heads and require a merge-migration. That's tractable but adds review surface.
3. **Doubles the migration backfill question**: PR #5's migration demotes existing `(RESOLVED, NULL)` rows to PENDING. A `(PENDING, value)` backfill would have to decide what to do — set `raw_return=NULL`? Promote status to RESOLVED? Neither is obvious.

The Pydantic-only approach delivers the contract at the API boundary (where DecisionPin actually lives) with zero migration cost and zero conflict with PR #5. Defense-in-depth at the DB layer is a separate, lower-priority future concern that can be added after both PRs land cleanly.

---

## 7. Test coverage

### 7.1 New tests in `server/tests/test_schemas_portfolio.py`

```python
import pytest
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
    """Spec §3 (mirrored on MemoryEntryOut)."""
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

The existing `test_memory_entry_out_accepts_pending_with_nulls` and `test_memory_entry_out_accepts_resolved` continue to pass (they construct valid states).

### 7.2 New integration test in `server/tests/test_portfolio_router.py`

```python
@pytest.mark.asyncio
async def test_ticker_detail_renders_pending_entry(client, db_session, monkeypatch):
    """A PENDING entry (raw_return=None) must round-trip through
    /portfolio/ticker/{ticker} without tripping the DecisionPin validator.
    Regression guard for spec §5.2 — the validator must not 500 on
    legitimate pending data."""
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-tp"))
    _add_entry(db_session, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
               rating="Buy", raw=None, status=MemoryEntryStatus.PENDING)
    await db_session.flush()

    async def fake_fetch(dashboard_dir, *, user_id, ticker, start, end):
        return [{"trade_date": "2024-05-10", "close": 100.0}]
    monkeypatch.setattr(portfolio_router, "_fetch_prices", fake_fetch)

    async with client as c:
        r = await c.get(
            "/portfolio/ticker/NVDA",
            headers={"Authorization": f"Bearer {make_jwt('gh-tp')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body["decisions"]) == 1
    assert body["decisions"][0]["status"] == "pending"
    assert body["decisions"][0]["raw_return"] is None
```

### 7.3 Why no test for the 500 path

A test that asserts `/portfolio/ticker/{ticker}` returns 500 when fed a `(PENDING, value)` DB row would require deliberately constructing that DB row — which on a clean branch (no PR #5) is possible via the unmodified `MemoryEntry` model, but is exactly the contract violation we're prohibiting. Testing the 500 path would mean asserting "when we plant bad data, the system catches it" — true but circular, and the schema-layer test (`test_decision_pin_rejects_pending_with_raw_return`) already covers the rejection at the validator level.

---

## 8. Files touched

| File | Change |
|------|--------|
| `server/app/schemas/portfolio.py` | Add `model_validator` to pydantic import; add `@model_validator(mode='after')` to `DecisionPin` and `MemoryEntryOut`. |
| `server/tests/test_schemas_portfolio.py` | Add 3 new tests (DecisionPin reject, DecisionPin accept-pending-null, MemoryEntryOut reject). |
| `server/tests/test_portfolio_router.py` | Add 1 integration test (`test_ticker_detail_renders_pending_entry`). |

No frontend changes (TypeScript already typed `raw_return: number | null`). No DB changes. No alembic migration. No diff to routers, services, models, or other tests.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **500 on a real user request.** If a future code path creates a `(PENDING, value)` MemoryEntry and the user hits `/portfolio/ticker/{ticker}`, the response is 500. | Spec §5.2 documents why this is the right behavior. Today the production path can't create the state. If a future endpoint adds the ability, the validator surfaces it loudly. |
| **Validator silently dropped if `model_config` is overridden later.** Pydantic v2 validators are inherited from BaseModel; misconfiguring `model_config` could in principle disable them. | Smoke test (`test_decision_pin_rejects_pending_with_raw_return`) acts as a regression guard. |
| **Confusion if/when v3+ #4 lands first.** `MemoryEntryStatusLiteral` derive-from-enum (v3+ #4) might restructure the literal type alias. The validator's `self.status == "pending"` comparison would still work (the alias resolves to the same string literal). | If #4 changes the comparison semantics, this PR's tests will fail loudly. |

---

## 10. Verification criteria

The implementation is done when all of the following are true:

1. `cd server && uv run pytest` — all existing tests + 4 new tests pass.
2. `test_decision_pin_rejects_pending_with_raw_return` and `test_memory_entry_out_rejects_pending_with_raw_return` raise `ValidationError` from construction.
3. `test_ticker_detail_renders_pending_entry` returns 200 with `decisions[0].status == "pending"` and `decisions[0].raw_return is None`.
4. `git diff main..HEAD --name-only -- server/app/models server/alembic server/app/services server/app/workers server/app/routers/portfolio.py` is empty (no DB, no migration, no router code, no service code, no worker — schema + tests only).
5. `git diff main..HEAD --name-only -- web` is empty (no frontend changes).
6. `cd server && uv run ruff check app/schemas/portfolio.py tests/test_schemas_portfolio.py tests/test_portfolio_router.py` reports clean.

---

## 11. References

- v3+ followup #3 in PR #3's body
- PR #5 (v3+ #2): the complementary RESOLVED-side invariant
- Pydantic v2 `@model_validator`: https://docs.pydantic.dev/latest/concepts/validators/#model-validators
- DecisionPin construction: `server/app/routers/portfolio.py:138-145`
- TypeScript interface (consumer): `web/lib/types.ts:82`

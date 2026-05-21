# Design: Watchlists (Wave 5.1)

**Date:** 2026-05-22
**Status:** Approved (design) — implementation plan to follow
**Owner:** erikgunawans
**Related:** First sub-project of Wave 5 (agentic monitoring + recommendations). Wave 5 was decomposed into four sub-projects: 5.1 Watchlists, 5.2 Monitor cron / trigger engine, 5.3 Recommendation feed UI, 5.4 (optional) Notifications. 5.1 is the foundation everything else depends on.

---

## 1. Context

After completing Wave 4 (auth UI, realtime opt-in, technical chart), the next direction is agentic monitoring — autonomously running TradingAgents analyses against tickers the user cares about, producing Buy/Hold/Sell signals on a schedule. The Monitor sub-project (5.2) needs a well-defined source of "which tickers to operate on." Today the system has an *implicit* set (`SELECT DISTINCT ticker FROM memory_entries WHERE user_id = ?`) — every ticker the user has ever analyzed. The brainstorm decision was to introduce an **explicit** watchlist instead, so the Monitor's cost (LLM tokens × watched tickers × frequency) is bounded by a deliberate user list, not by analysis history that grows monotonically.

## 2. Goals

- A new `watchlist_items` table stores per-user, per-ticker entries with optional notes and an added timestamp.
- A `/watchlist` page lets the user list, add, edit notes for, and remove watched tickers.
- A `Watchlist` item in the existing nav surfaces the page from anywhere in the app.
- The API surface for the watchlist (`GET/POST/PATCH/DELETE /watchlist`) is fully scoped to the current user; cross-user reads/writes are invisible to each other.
- All visuals match the existing Axiara dark theme (tokens established by PRs #16, #22, #23, #24).
- Migration up + down round-trips cleanly in the test suite.

## 3. Non-goals

- Multiple named watchlists per user — flat single list, deferred until usage justifies it.
- Alert thresholds (`alert_above_price`, `alert_below_price`) — Wave 5.2 Monitor design will propose trigger semantics alongside the data shape, not piecemeal here.
- "Add to watchlist" buttons sprinkled on `/portfolio/[ticker]` and `/history/[runId]` — additive nice-to-have for a followup PR.
- Latest-signal-per-ticker display on each watchlist row — depends on Wave 5.2 (Monitor signals don't exist yet).
- Reorderable rows / drag-sort — flat ordering by `added_at DESC`, no manual ordering.
- Sharing watchlists between users — single-tenant deploy.
- Import/export from a CSV or TradingView — minimal v1.
- Server-side caching of the watchlist response — DB query is sub-millisecond at expected scale.

## 4. Architecture

One new table on the server (`watchlist_items`), one new router with 4 CRUD endpoints, one new web page with two client components, and a new nav item. No new dependencies on either side.

```
              ┌────────────────────────────────────────────────────────┐
              │  Web (Next.js)                                          │
              │   /watchlist (server component, redirects if unauth)   │
              │     ├─► api.listWatchlist()                            │
              │     ├─► WatchlistTable (client)                         │
              │     │     - row click → /portfolio/[ticker]            │
              │     │     - inline notes edit (textarea on click)      │
              │     │     - remove → modal confirm → DELETE             │
              │     └─► QuickAddForm (client)                          │
              │           - ticker input (uppercased onChange)         │
              │           - optional notes textarea                    │
              │           - submit → POST; 409 → inline error          │
              │                                                         │
              │   Nav: new "Watchlist" item (Bookmark icon)            │
              └────────────────────────────────────────────────────────┘
                                          │
                                          ▼
              ┌────────────────────────────────────────────────────────┐
              │  Server (FastAPI)                                       │
              │    GET    /watchlist                                    │
              │    POST   /watchlist  body {ticker, notes?}             │
              │    PATCH  /watchlist/{ticker}  body {notes}             │
              │    DELETE /watchlist/{ticker}                           │
              │                                                         │
              │  Postgres watchlist_items:                              │
              │    id          UUID PK                                  │
              │    user_id     UUID FK → users.id (ON DELETE CASCADE)  │
              │    ticker      VARCHAR(32)                              │
              │    notes       VARCHAR(500) NULL                        │
              │    added_at    TIMESTAMPTZ DEFAULT NOW()                │
              │    UNIQUE (user_id, ticker) — uq_watchlist_user_ticker │
              │    INDEX (user_id, added_at DESC) — ix_watchlist_user…│
              └────────────────────────────────────────────────────────┘
```

## 5. File structure

| File | Action | Responsibility |
|---|---|---|
| `server/alembic/versions/<sha>_add_watchlist_items.py` | create | Migration: create `watchlist_items` with the 5 columns + unique constraint + FK + composite index. |
| `server/app/models/watchlist.py` | create | SQLAlchemy `WatchlistItem` model. |
| `server/app/schemas/watchlist.py` | create | Pydantic `WatchlistItemOut`, `WatchlistAdd`, `WatchlistNotesUpdate`. |
| `server/app/routers/watchlist.py` | create | FastAPI router with the 4 endpoints. |
| `server/app/main.py` | modify | Register the new router. |
| `server/tests/test_watchlist.py` | create | Pytest: CRUD happy paths, duplicate → 409, invalid ticker → 422, scoped-to-user, lowercase ticker rejected. |
| `web/app/watchlist/page.tsx` | create | Server component; fetches watchlist + renders Nav + QuickAddForm + WatchlistTable. |
| `web/app/watchlist/WatchlistTable.tsx` | create | Client. Table rows + inline notes edit + remove-with-modal-confirm. |
| `web/app/watchlist/QuickAddForm.tsx` | create | Client. Add-ticker form with 409 conflict handling. |
| `web/lib/api.ts` | modify | Add `listWatchlist`, `addToWatchlist`, `removeFromWatchlist`, `updateWatchlistNotes`. |
| `web/components/Nav.tsx` | modify | Add `{ href: "/watchlist", label: "Watchlist", icon: Bookmark }` to `NAV_ITEMS`. |
| `web/tests/e2e/watchlist.spec.ts` | create | Playwright: add ticker, edit notes, remove via modal, duplicate-add inline error. |

## 6. Decisions resolved during spec-writing

These were §7 open questions in the design presentation; baking in answers:

1. **Remove confirmation = modal yes-or-no.** Toast-with-undo is nicer UX but requires a Toaster provider in the layout (new infrastructure for a single use case). Modal is simpler, ships in v1, can upgrade to toast later when other surfaces (e.g., bulk operations on /history) need similar UX.

2. **Notes character limit = 500 chars.** Enforced at both the Pydantic schema (max_length=500) and the DB column (VARCHAR(500)). Long enough for "watching for breakout above 5500; entered position 2026-04 at 5230." Short enough to keep DB rows lean.

3. **Ticker casing**: client form uppercases on `onChange`; server rejects lowercase via the existing `TICKER_RE` validator (which requires `[A-Z]` start). Defense in depth — UX nice, API correctness enforced.

## 7. Server-side concrete shape

### Migration

```python
"""add_watchlist_items

Revision ID: <new>
Revises: c2d3e4f5a6b7
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op

revision = "<new>"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )
    op.create_index(
        "ix_watchlist_user_added",
        "watchlist_items",
        ["user_id", sa.text("added_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_user_added", "watchlist_items")
    op.drop_table("watchlist_items")
```

### Model (`server/app/models/watchlist.py`)

```python
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )
```

### Schemas (`server/app/schemas/watchlist.py`)

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WatchlistItemOut(BaseModel):
    id: UUID
    ticker: str
    notes: str | None
    added_at: datetime

    model_config = {"from_attributes": True}


class WatchlistAdd(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=500)


class WatchlistNotesUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=500)
```

### Router (`server/app/routers/watchlist.py`)

```python
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.watchlist import (
    WatchlistAdd,
    WatchlistItemOut,
    WatchlistNotesUpdate,
)
from app.services.user_root import TICKER_RE, check_segment

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistItem]:
    """Return user's watchlist, newest-added first."""
    result = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.added_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_to_watchlist(
    body: WatchlistAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Add a ticker to the user's watchlist. 409 on duplicate, 422 on invalid ticker."""
    check_segment("ticker", body.ticker, TICKER_RE)
    item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user.id,
        ticker=body.ticker,
        notes=body.notes,
    )
    db.add(item)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "ticker already on watchlist", "ticker": body.ticker},
        )
    return item


@router.patch("/{ticker}", response_model=WatchlistItemOut)
async def update_notes(
    body: WatchlistNotesUpdate,
    ticker: str = PathParam(..., pattern=TICKER_RE.pattern),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Replace the notes for a watched ticker."""
    item = (
        await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user.id,
                WatchlistItem.ticker == ticker,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=404, detail={"error": "ticker not on watchlist"}
        )
    item.notes = body.notes
    return item


@router.delete("/{ticker}", status_code=204)
async def remove_from_watchlist(
    ticker: str = PathParam(..., pattern=TICKER_RE.pattern),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a ticker from the user's watchlist."""
    result = await db.execute(
        sa.delete(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=404, detail={"error": "ticker not on watchlist"}
        )
```

### Router registration

In `server/app/main.py`, alongside the other `app.include_router(...)` calls, add:

```python
from app.routers import watchlist
app.include_router(watchlist.router)
```

## 8. Web-side concrete shape

### `web/app/watchlist/page.tsx` (server component)

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import QuickAddForm from "./QuickAddForm";
import WatchlistTable from "./WatchlistTable";

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const items = await api.listWatchlist();

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <PageHeader
          eyebrow="Tickers"
          title="Watchlist"
          description="Tickers the agentic monitor will track for buy/sell signals."
        />
        <div className="mt-6">
          <QuickAddForm />
        </div>
        <div className="mt-6">
          <WatchlistTable initialItems={items} />
        </div>
      </main>
    </>
  );
}
```

### `WatchlistTable.tsx` + `QuickAddForm.tsx`

Sketch only — full code lives in the plan. Both client components, both use Axiara tokens, both maintain optimistic local state with server reconciliation. `WatchlistTable` opens a `<dialog>` element (native HTML modal, no new dependency) for the remove confirmation.

### `web/lib/api.ts` additions

```typescript
listWatchlist: () => get<WatchlistItemOut[]>("/watchlist"),
addToWatchlist: (ticker: string, notes?: string | null) =>
  post<WatchlistItemOut>("/watchlist", { ticker, notes }),
updateWatchlistNotes: (ticker: string, notes: string | null) =>
  patch<WatchlistItemOut>(`/watchlist/${encodeURIComponent(ticker)}`, { notes }),
removeFromWatchlist: (ticker: string) =>
  del(`/watchlist/${encodeURIComponent(ticker)}`),
```

Helpers `patch<T>` and `del` may already exist in `api.ts` — if not, they need to be added (same pattern as the existing `get<T>`/`post<T>`).

### `Nav.tsx` modification

Add to `NAV_ITEMS`:

```typescript
{ href: "/watchlist", label: "Watchlist", icon: Bookmark },
```

Import `Bookmark` from `lucide-react`.

## 9. Testing

| Test | Location | Type |
|---|---|---|
| GET /watchlist returns empty list for new user | `server/tests/test_watchlist.py` | pytest |
| POST /watchlist creates row, 201, returns item | same | pytest |
| POST duplicate ticker returns 409 | same | pytest |
| POST lowercase / invalid ticker returns 422 | same | pytest |
| PATCH /watchlist/{ticker} updates notes | same | pytest |
| PATCH on missing ticker returns 404 | same | pytest |
| DELETE removes row, returns 204 | same | pytest |
| DELETE on missing ticker returns 404 | same | pytest |
| All operations scoped to current user (other user's rows invisible) | same | pytest |
| Migration up + down round-trips | existing migration test infrastructure | pytest |
| /watchlist page renders empty state with no items | `web/tests/e2e/watchlist.spec.ts` | Playwright |
| Add ticker via QuickAddForm; row appears | same | Playwright |
| Edit notes inline; persists across reload | same | Playwright |
| Remove via modal-confirm; row disappears | same | Playwright |
| Duplicate add shows inline error | same | Playwright |

## 10. Acceptance criteria

The implementation is done when all of these are true:

- [ ] Migration creates `watchlist_items` with the 5 columns, FK to users (ON DELETE CASCADE), unique constraint on (user_id, ticker), and the composite index.
- [ ] All 4 endpoints (`GET`, `POST`, `PATCH`, `DELETE`) behave per §7 specs.
- [ ] Server tests cover happy paths + error codes + user scoping (10 tests minimum).
- [ ] `/watchlist` page renders with `Nav` + header + add form + table.
- [ ] `Watchlist` appears in the nav between Portfolio and the right-side controls.
- [ ] Adding a ticker optimistically prepends the row + persists.
- [ ] Adding a duplicate shows an inline "already on watchlist" error.
- [ ] Notes are inline-editable with a textarea; save on blur or Enter.
- [ ] Remove opens a `<dialog>` modal asking "Remove BBCA.JK from your watchlist?" with Cancel + Remove buttons; Remove persists + removes the row.
- [ ] Clicking a ticker in the table navigates to `/portfolio/[ticker]`.
- [ ] Empty state shows "Add a ticker above to start watching."
- [ ] Lowercase ticker rejected with a friendly client-side error before submission.
- [ ] Playwright e2e covers add + edit + remove + duplicate-error.
- [ ] Migration up + down round-trips cleanly in tests.

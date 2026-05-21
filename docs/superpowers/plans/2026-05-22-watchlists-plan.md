# Watchlists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-user explicit watchlist — `watchlist_items` table, 4 CRUD endpoints, a dedicated `/watchlist` page with inline add / edit-notes / remove flows, and a new "Watchlist" nav item — as the foundation for Wave 5's agentic monitoring (5.2+).

**Architecture:** New SQLAlchemy model + Alembic migration on the server side, FastAPI router with 4 endpoints (`GET/POST/PATCH/DELETE`) all scoped to the current user via existing `get_current_user`. Web side: new `/watchlist` page (server component) renders `QuickAddForm` + `WatchlistTable` (both client components); `Nav` gains a `Watchlist` item. No new dependencies.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic migrations + PyJWT (existing); Next.js 15 server/client components + Tailwind + Lucide icons + Playwright e2e + Vitest available but unused for this feature.

**Spec:** [`docs/superpowers/plans/2026-05-22-watchlists-design.md`](./2026-05-22-watchlists-design.md)

---

## Before You Start

This plan assumes you can answer "yes" to all of these:

- You can run `cd server && uv run pytest -q` and have all baseline tests pass.
- You can run `cd web && npm run build` (with NEXTAUTH_SECRET set for static build).
- You have `docker compose` available locally — only used for an optional dev smoke.

Confirmed during plan-writing:

- **Alembic head** is `c2d3e4f5a6b7` (auth-UI migration). New migration's `down_revision = "c2d3e4f5a6b7"`.
- **`web/lib/api.ts`** has `get<T>(path)` + `post<T>(path, body)` helpers. **Does NOT have `patch<T>` or `del`** — must be added in Task 4.
- **`server/app/main.py`** uses `from app.routers import X as X_router` + `app.include_router(X_router.router)`. Watchlist router registers the same way.
- **`PageHeader`** is at `web/components/PageHeader.tsx` with default export. Already used by `/history`.
- **`TICKER_RE`** = `re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")` in `server/app/services/user_root.py:14` — uppercase-start, 1-12 chars.

---

## ⚠️ Worktree discipline — mandatory pre-commit verification

The Wave 4 item 2 + 3 implementers each landed in a worktree that was initialized at a stale upstream commit. The item 2 implementer accidentally committed to LOCAL main; item 3's implementer caught the mismatch and `reset --hard`'d to the plan-commit SHA before working. Same discipline applies here.

**Before EVERY commit, run all three checks:**

```bash
pwd                                                              # MUST start with `.claude/worktrees/agent-`
git rev-parse --abbrev-ref HEAD                                  # MUST start with `worktree-agent-` or `agent-` (not `main`)
git -C /Users/erikgunawansupriatna/TradingAgents rev-parse main  # MUST be d009119... (plan-commit SHA) — unchanged
```

If ANY check fails, STOP and report BLOCKED. If your worktree's HEAD is at an unrelated upstream SHA (e.g., `61522e1`), the first remediation is `git fetch --all && git reset --hard d009119` BEFORE writing any code.

---

## Phase 1 — Setup

### Task 1: Create the feature branch

**Files:** none (git only).

- [ ] **Step 1: Sync local main**

```bash
cd /Users/erikgunawansupriatna/TradingAgents
git fetch fork
git checkout main
git pull fork main
```

Expected: `Already up to date.` or fast-forward to fork/main HEAD (which includes `d009119` — the watchlists plan).

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b feature/watchlists
```

Expected: `Switched to a new branch 'feature/watchlists'`.

---

## Phase 2 — Server: migration + model + schemas + router + tests

### Task 2: Write failing pytest tests

**Files:**
- Create: `server/tests/test_watchlist.py`

- [ ] **Step 1: Create the test file**

```python
# server/tests/test_watchlist.py
"""End-to-end tests of /watchlist endpoints (CRUD + scoping)."""
import uuid

import pytest
from httpx import AsyncClient

from app.models.user import User
from app.models.watchlist import WatchlistItem


@pytest.mark.asyncio
async def test_empty_list_for_new_user(async_client_authed):
    """GET /watchlist returns [] for a user with no rows."""
    res = await async_client_authed.get("/watchlist")
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_add_ticker_returns_201_and_row(async_client_authed):
    """POST /watchlist {ticker} returns 201 + persisted row."""
    res = await async_client_authed.post(
        "/watchlist", json={"ticker": "AAPL", "notes": "tracking earnings"}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["notes"] == "tracking earnings"
    assert "id" in body
    assert "added_at" in body


@pytest.mark.asyncio
async def test_add_without_notes_succeeds(async_client_authed):
    """POST /watchlist with notes omitted → notes is null in response."""
    res = await async_client_authed.post("/watchlist", json={"ticker": "MSFT"})
    assert res.status_code == 201
    assert res.json()["notes"] is None


@pytest.mark.asyncio
async def test_duplicate_returns_409(async_client_authed):
    """POST /watchlist with a ticker already present → 409."""
    await async_client_authed.post("/watchlist", json={"ticker": "GOOG"})
    res = await async_client_authed.post(
        "/watchlist", json={"ticker": "GOOG", "notes": "second attempt"}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "ticker already on watchlist"


@pytest.mark.asyncio
async def test_lowercase_ticker_returns_422(async_client_authed):
    """POST /watchlist with lowercase ticker → 422 (TICKER_RE rejects)."""
    res = await async_client_authed.post("/watchlist", json={"ticker": "aapl"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invalid_ticker_too_long_returns_422(async_client_authed):
    """POST /watchlist with a 13-char ticker → 422."""
    res = await async_client_authed.post(
        "/watchlist", json={"ticker": "ABCDEFGHIJKLM"}  # 13 chars, TICKER_RE max is 12
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_list_returns_most_recent_first(async_client_authed):
    """GET /watchlist orders by added_at DESC."""
    for ticker in ["AAA", "BBB", "CCC"]:
        await async_client_authed.post("/watchlist", json={"ticker": ticker})
    res = await async_client_authed.get("/watchlist")
    tickers = [item["ticker"] for item in res.json()]
    assert tickers == ["CCC", "BBB", "AAA"]  # most-recent-added first


@pytest.mark.asyncio
async def test_patch_updates_notes(async_client_authed):
    """PATCH /watchlist/{ticker} {notes} replaces notes."""
    await async_client_authed.post(
        "/watchlist", json={"ticker": "TSLA", "notes": "old note"}
    )
    res = await async_client_authed.patch(
        "/watchlist/TSLA", json={"notes": "new thesis"}
    )
    assert res.status_code == 200
    assert res.json()["notes"] == "new thesis"


@pytest.mark.asyncio
async def test_patch_missing_ticker_returns_404(async_client_authed):
    """PATCH /watchlist/{ticker} for unknown ticker → 404."""
    res = await async_client_authed.patch(
        "/watchlist/NEVER", json={"notes": "anything"}
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_row(async_client_authed):
    """DELETE /watchlist/{ticker} → 204 and the row is gone."""
    await async_client_authed.post("/watchlist", json={"ticker": "NVDA"})
    res = await async_client_authed.delete("/watchlist/NVDA")
    assert res.status_code == 204
    list_res = await async_client_authed.get("/watchlist")
    assert list_res.json() == []


@pytest.mark.asyncio
async def test_delete_missing_ticker_returns_404(async_client_authed):
    """DELETE /watchlist/{ticker} for unknown ticker → 404."""
    res = await async_client_authed.delete("/watchlist/NEVER")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_scoped_to_current_user(async_client_authed, db_session, authed_user):
    """Another user's watchlist rows are invisible — current user sees only their own."""
    other = User(id=uuid.uuid4(), github_id="other-user-999", email=None)
    db_session.add(other)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=other.id, ticker="OTHER"))
    await db_session.flush()
    # Current user adds their own ticker:
    await async_client_authed.post("/watchlist", json={"ticker": "OWN"})

    res = await async_client_authed.get("/watchlist")
    tickers = [item["ticker"] for item in res.json()]
    assert tickers == ["OWN"], "other user's ticker should not leak"
```

> **Fixture note**: if `async_client_authed` + `authed_user` aren't defined in `server/tests/conftest.py`, copy the inline pattern from `server/tests/test_runs_active_count.py` (Wave 4 item 2 set this precedent — inline `client` fixture + `make_jwt()` + local `authed_user`). Adjust references accordingly.

- [ ] **Step 2: Run to verify all 12 tests fail**

```bash
cd server && uv run pytest tests/test_watchlist.py -v 2>&1 | tail -20
```

Expected: 12 failures, likely with `ImportError: cannot import name 'WatchlistItem' from 'app.models.watchlist'` (file doesn't exist) and/or 404 on the endpoints.

No commit yet — combined with Task 3.

---

### Task 3: Implement migration + model + schemas + router + main.py registration

**Files:**
- Create: `server/alembic/versions/d3e4f5a6b7c8_add_watchlist_items.py` (the file name uses any next-SHA-like slug; `d3e4f5a6b7c8` is suggested)
- Create: `server/app/models/watchlist.py`
- Create: `server/app/schemas/watchlist.py`
- Create: `server/app/routers/watchlist.py`
- Modify: `server/app/main.py`

- [ ] **Step 1: Write the migration**

Create `server/alembic/versions/d3e4f5a6b7c8_add_watchlist_items.py`:

```python
"""add_watchlist_items

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
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
    op.drop_index("ix_watchlist_user_added", table_name="watchlist_items")
    op.drop_table("watchlist_items")
```

- [ ] **Step 2: Write the model**

Create `server/app/models/watchlist.py`:

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

- [ ] **Step 3: Write the schemas**

Create `server/app/schemas/watchlist.py`:

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

- [ ] **Step 4: Write the router**

Create `server/app/routers/watchlist.py`:

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
    """Add a ticker to the watchlist. 409 on duplicate, 422 on invalid ticker."""
    try:
        check_segment("ticker", body.ticker, TICKER_RE)
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "invalid ticker", "ticker": body.ticker})

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
    """Replace notes for a watched ticker."""
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

- [ ] **Step 5: Register the router in main.py**

Open `server/app/main.py`. Find the existing imports + `app.include_router` calls (around lines 3-10) and add the watchlist:

```python
from app.routers import watchlist as watchlist_router
# ... after the existing include_router calls:
app.include_router(watchlist_router.router)
```

- [ ] **Step 6: Run migration + new tests + full suite**

```bash
cd server
uv run alembic upgrade head
uv run pytest tests/test_watchlist.py -v
uv run pytest -q
```

Expected:
- Migration applies cleanly; HEAD is now `d3e4f5a6b7c8`.
- 12 new watchlist tests pass.
- Full suite: previous baseline + 12 (likely 177 + 12 = 189). No regressions.

- [ ] **Step 7: Verify migration round-trips down + up**

```bash
cd server
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: both succeed; final HEAD is `d3e4f5a6b7c8`.

- [ ] **Step 8: Worktree discipline + commit**

Run the three pre-commit checks (from the "Before You Start" preamble). All must pass.

```bash
git add server/alembic/versions/d3e4f5a6b7c8_add_watchlist_items.py \
        server/app/models/watchlist.py \
        server/app/schemas/watchlist.py \
        server/app/routers/watchlist.py \
        server/app/main.py \
        server/tests/test_watchlist.py
git commit -m "feat(server): watchlist CRUD endpoints + watchlist_items table

Migration adds watchlist_items (id, user_id, ticker, notes, added_at)
with UNIQUE(user_id, ticker) and a (user_id, added_at DESC) index.
FK to users.id with ON DELETE CASCADE — removing a user removes
their watchlist.

Endpoints:
- GET    /watchlist                    -> list, newest first
- POST   /watchlist                    -> add (409 dup, 422 invalid)
- PATCH  /watchlist/{ticker}           -> replace notes (404 missing)
- DELETE /watchlist/{ticker}           -> remove (404 missing)

All endpoints scoped to current user. Ticker validated via existing
TICKER_RE (uppercase, 1-12 chars). Notes max 500 chars at both
Pydantic + DB column levels.

12 new pytest tests cover happy paths, duplicate (409), lowercase
+ too-long ticker (422), most-recent-first ordering, patch + delete
not-found (404), and user-scoping (other user's rows invisible)."
```

---

## Phase 3 — Web API client

### Task 4: Add `patch<T>` + `del` helpers + watchlist methods

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add the helper functions**

Open `web/lib/api.ts`. After the existing `post<T>` function (around line 76 — find with `grep -n "async function post" web/lib/api.ts`), add:

```typescript
async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: {
      Authorization: await bearer(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const respBody = await parseBody(res);
    throw new ApiError(res.status, respBody, `api ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) {
    const respBody = await parseBody(res);
    throw new ApiError(res.status, respBody, `api ${path} failed: ${res.status}`);
  }
}
```

- [ ] **Step 2: Add `WatchlistItemOut` type import**

At the top of `web/lib/api.ts`, add `WatchlistItemOut` to the type imports from `@/lib/types` (it'll exist after Task 5 runs codegen):

```typescript
import type {
  // ... existing imports ...
  WatchlistItemOut,
} from "@/lib/types";
```

- [ ] **Step 3: Add watchlist methods to the `api` object**

In the `api` object definition (around line 79), add the 4 watchlist methods. Place them between `countActiveRuns` and `portfolioSummary` to keep them grouped:

```typescript
listWatchlist: () => get<WatchlistItemOut[]>("/watchlist"),
addToWatchlist: (ticker: string, notes?: string | null) =>
  post<WatchlistItemOut>("/watchlist", { ticker, notes: notes ?? null }),
updateWatchlistNotes: (ticker: string, notes: string | null) =>
  patch<WatchlistItemOut>(`/watchlist/${encodeURIComponent(ticker)}`, { notes }),
removeFromWatchlist: (ticker: string) =>
  del(`/watchlist/${encodeURIComponent(ticker)}`),
```

- [ ] **Step 4: Regenerate OpenAPI types**

```bash
cd web && npm run codegen
```

Expected: `web/lib/openapi-types.ts` updates to include `WatchlistItemOut`, `WatchlistAdd`, `WatchlistNotesUpdate`.

- [ ] **Step 5: Add `WatchlistItemOut` export to `web/lib/types.ts`**

Open `web/lib/types.ts`. Add alongside the other type exports:

```typescript
export type WatchlistItemOut = components["schemas"]["WatchlistItemOut"];
```

- [ ] **Step 6: Verify TypeScript builds**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -5
```

Expected: build succeeds, no type errors.

- [ ] **Step 7: Worktree discipline + commit**

```bash
git add web/lib/api.ts web/lib/types.ts web/lib/openapi-types.ts
git commit -m "feat(web): add patch<T> + del helpers + watchlist api methods

Adds patch<T>(path, body) and del(path) helpers next to the existing
get<T>/post<T> in api.ts — same Bearer + JSON pattern, same ApiError
shape.

api object gains 4 watchlist methods:
- listWatchlist()        -> WatchlistItemOut[]
- addToWatchlist(ticker, notes?) -> WatchlistItemOut
- updateWatchlistNotes(ticker, notes) -> WatchlistItemOut
- removeFromWatchlist(ticker)   -> void

Regenerates openapi-types.ts; exports WatchlistItemOut from
web/lib/types.ts."
```

---

## Phase 4 — Web UI

### Task 5: Create the `/watchlist` page + components

**Files:**
- Create: `web/app/watchlist/page.tsx`
- Create: `web/app/watchlist/QuickAddForm.tsx`
- Create: `web/app/watchlist/WatchlistTable.tsx`

- [ ] **Step 1: Create the page (server component)**

Create `web/app/watchlist/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import QuickAddForm from "./QuickAddForm";
import WatchlistTable from "./WatchlistTable";

export const metadata = { title: "Watchlist · TradingAgents" };

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
        <div className="mt-6 space-y-6">
          <QuickAddForm />
          <WatchlistTable initialItems={items} />
        </div>
      </main>
    </>
  );
}
```

- [ ] **Step 2: Create QuickAddForm**

Create `web/app/watchlist/QuickAddForm.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";

const TICKER_PATTERN = /^[A-Z][A-Z0-9.\-]{0,11}$/;

export default function QuickAddForm() {
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!TICKER_PATTERN.test(ticker)) {
      setError("Ticker must be uppercase letters, digits, '.' or '-' (1-12 chars).");
      return;
    }

    setSubmitting(true);
    try {
      await api.addToWatchlist(ticker, notes.trim() || null);
      setTicker("");
      setNotes("");
      router.refresh(); // Re-fetch the server component's data.
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(`${ticker} is already on your watchlist.`);
      } else if (e instanceof ApiError && e.status === 422) {
        setError("Server rejected this ticker. Use only uppercase letters, digits, '.' or '-'.");
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border border-border/60 bg-surface/40 p-4 backdrop-blur-sm"
    >
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          name="ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="e.g. BBCA.JK"
          aria-label="Ticker"
          className="h-10 w-full max-w-xs rounded-lg border border-border/60 bg-surface/40 px-3 font-mono text-sm text-fg placeholder:text-fg-subtle/70 focus:border-brand/60 focus:outline-none focus:ring-1 focus:ring-brand/40"
          required
        />
        <input
          name="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional notes (e.g. watching for breakout)"
          aria-label="Notes"
          maxLength={500}
          className="h-10 flex-1 rounded-lg border border-border/60 bg-surface/40 px-3 text-sm text-fg placeholder:text-fg-subtle/70 focus:border-brand/60 focus:outline-none focus:ring-1 focus:ring-brand/40"
        />
        <button
          type="submit"
          disabled={submitting || !ticker}
          className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-brand/60 bg-brand/10 px-4 text-sm font-medium text-brand transition-colors hover:bg-brand/15 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" aria-hidden />
          Add
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error}
        </p>
      )}
    </form>
  );
}
```

- [ ] **Step 3: Create WatchlistTable**

Create `web/app/watchlist/WatchlistTable.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Pencil, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { WatchlistItemOut } from "@/lib/types";
import { cn } from "@/lib/cn";

export default function WatchlistTable({
  initialItems,
}: {
  initialItems: WatchlistItemOut[];
}) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [editing, setEditing] = useState<string | null>(null); // ticker
  const [editNotes, setEditNotes] = useState("");
  const [removeTarget, setRemoveTarget] = useState<string | null>(null); // ticker
  const dialogRef = useRef<HTMLDialogElement>(null);

  // Sync local state when server-provided items change (router.refresh()).
  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  // Open the <dialog> when removeTarget is set.
  useEffect(() => {
    if (removeTarget !== null && dialogRef.current) {
      dialogRef.current.showModal();
    }
  }, [removeTarget]);

  async function saveNotes(ticker: string) {
    const next = editNotes.trim() || null;
    try {
      await api.updateWatchlistNotes(ticker, next);
      setItems((prev) =>
        prev.map((i) => (i.ticker === ticker ? { ...i, notes: next } : i)),
      );
    } catch (e) {
      console.error("update notes failed", e);
    } finally {
      setEditing(null);
      setEditNotes("");
    }
  }

  async function confirmRemove() {
    if (!removeTarget) return;
    const ticker = removeTarget;
    setRemoveTarget(null);
    dialogRef.current?.close();
    try {
      await api.removeFromWatchlist(ticker);
      setItems((prev) => prev.filter((i) => i.ticker !== ticker));
    } catch (e) {
      console.error("remove failed", e);
      router.refresh(); // Reconcile.
    }
  }

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-border/60 bg-surface/40 px-4 py-10 text-center text-sm text-fg-muted backdrop-blur-sm">
        Add a ticker above to start watching.
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border/60 bg-surface/40 backdrop-blur-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/40 text-left">
              <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
                Ticker
              </th>
              <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
                Notes
              </th>
              <th className="px-4 py-3 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
                Added
              </th>
              <th className="w-24 px-4 py-3" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="border-b border-border/30 transition-colors last:border-0 hover:bg-surface/60"
              >
                <td className="px-4 py-2.5 font-mono">
                  <Link
                    href={`/portfolio/${encodeURIComponent(item.ticker)}`}
                    className="text-fg hover:text-brand"
                  >
                    {item.ticker}
                  </Link>
                </td>
                <td className="px-4 py-2.5 text-fg-muted">
                  {editing === item.ticker ? (
                    <textarea
                      autoFocus
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                      onBlur={() => saveNotes(item.ticker)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          saveNotes(item.ticker);
                        } else if (e.key === "Escape") {
                          setEditing(null);
                          setEditNotes("");
                        }
                      }}
                      maxLength={500}
                      rows={2}
                      className="w-full rounded border border-border bg-surface/60 px-2 py-1 text-sm text-fg focus:border-brand/60 focus:outline-none"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(item.ticker);
                        setEditNotes(item.notes ?? "");
                      }}
                      className="flex w-full items-start gap-2 text-left hover:text-fg"
                    >
                      <span className={cn(item.notes ? "" : "italic text-fg-subtle")}>
                        {item.notes || "Click to add notes"}
                      </span>
                      <Pencil className="h-3 w-3 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                    </button>
                  )}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-fg-subtle">
                  {new Date(item.added_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-2.5">
                  <button
                    type="button"
                    onClick={() => setRemoveTarget(item.ticker)}
                    aria-label={`Remove ${item.ticker} from watchlist`}
                    className="inline-flex h-7 w-7 items-center justify-center rounded text-fg-subtle transition-colors hover:bg-danger/10 hover:text-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dialog
        ref={dialogRef}
        onClose={() => setRemoveTarget(null)}
        className="rounded-xl border border-border/60 bg-surface p-6 backdrop:bg-black/60 backdrop-blur-sm text-fg"
      >
        <h3 className="mb-2 text-sm font-semibold">Remove from watchlist?</h3>
        <p className="mb-4 text-sm text-fg-muted">
          Remove <span className="font-mono">{removeTarget}</span> from your watchlist?
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              dialogRef.current?.close();
              setRemoveTarget(null);
            }}
            className="rounded-lg border border-border/60 bg-surface/40 px-3 py-1.5 text-sm text-fg-muted hover:text-fg"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={confirmRemove}
            className="rounded-lg border border-danger/60 bg-danger/10 px-3 py-1.5 text-sm text-danger hover:bg-danger/15"
          >
            Remove
          </button>
        </div>
      </dialog>
    </>
  );
}
```

- [ ] **Step 4: Build + verify**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -10
```

Expected: build succeeds; route list includes `/watchlist` (ƒ — server-rendered on demand).

- [ ] **Step 5: Worktree discipline + commit**

```bash
git add web/app/watchlist/page.tsx \
        web/app/watchlist/QuickAddForm.tsx \
        web/app/watchlist/WatchlistTable.tsx
git commit -m "feat(web): /watchlist page (server) + QuickAddForm + WatchlistTable

- page.tsx (server component) fetches the watchlist server-side, redirects
  unauth users, renders Nav + PageHeader + QuickAddForm + WatchlistTable.
- QuickAddForm (client) uppercases ticker onChange, validates client-side
  against TICKER_RE before submit, calls api.addToWatchlist, handles 409
  conflict + 422 invalid with inline error, refreshes the page on success
  to pick up the new server-rendered list.
- WatchlistTable (client) renders rows with ticker (linked to portfolio),
  inline-editable notes (textarea on click, save on blur/Enter, cancel on
  Escape), formatted added_at, and a remove button. Remove opens a native
  <dialog> modal asking for confirmation; Confirm calls api.removeFromWatchlist
  with optimistic local state update + router.refresh fallback on error.
- Empty state when no items: 'Add a ticker above to start watching.'"
```

---

### Task 6: Add the Watchlist item to Nav

**Files:**
- Modify: `web/components/Nav.tsx`

- [ ] **Step 1: Import Bookmark icon + add nav item**

Open `web/components/Nav.tsx`. Find the imports near the top:

```typescript
import { Activity, History, PlayCircle, PieChart } from "lucide-react";
```

Add `Bookmark`:

```typescript
import { Activity, Bookmark, History, PlayCircle, PieChart } from "lucide-react";
```

Find the `NAV_ITEMS` array:

```typescript
const NAV_ITEMS = [
  { href: "/history", label: "History", icon: History },
  { href: "/live", label: "Live", icon: Activity },
  { href: "/launch", label: "Launch", icon: PlayCircle },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
];
```

Add the watchlist entry between Portfolio and any sentinel — keep Watchlist last in the list:

```typescript
const NAV_ITEMS = [
  { href: "/history", label: "History", icon: History },
  { href: "/live", label: "Live", icon: Activity },
  { href: "/launch", label: "Launch", icon: PlayCircle },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
  { href: "/watchlist", label: "Watchlist", icon: Bookmark },
];
```

- [ ] **Step 2: Build verification**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -3
```

Expected: clean.

- [ ] **Step 3: Worktree discipline + commit**

```bash
git add web/components/Nav.tsx
git commit -m "feat(web): add Watchlist to nav (Bookmark icon, last item)

Sits after Portfolio in the primary nav. Uses lucide-react's Bookmark
icon which fits the 'something I want to keep tabs on' semantic."
```

---

## Phase 5 — E2E

### Task 7: Playwright e2e for the watchlist flow

**Files:**
- Create: `web/tests/e2e/watchlist.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/watchlist", () => {
  test("empty state renders for a new user", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    await expect(page.getByRole("heading", { name: "Watchlist" })).toBeVisible();
    await expect(page.getByText("Add a ticker above to start watching.")).toBeVisible();
  });

  test("add a ticker via QuickAddForm; row appears", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    await page.getByLabel("Ticker").fill("AAPL");
    await page.getByLabel("Notes").fill("tracking earnings");
    await page.getByRole("button", { name: /^add$/i }).click();

    // Wait for router.refresh() to repaint the table.
    await expect(page.getByRole("link", { name: "AAPL" })).toBeVisible();
    await expect(page.getByText("tracking earnings")).toBeVisible();
  });

  test("duplicate add shows inline error", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Add first instance (clean state assumed from prior test or fresh DB).
    await page.getByLabel("Ticker").fill("DUPE");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "DUPE" })).toBeVisible();

    // Try to add again.
    await page.getByLabel("Ticker").fill("DUPE");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("alert")).toContainText(/already on your watchlist/i);
  });

  test("lowercase ticker is auto-uppercased on input", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    const tickerInput = page.getByLabel("Ticker");
    await tickerInput.fill("nvda");
    await expect(tickerInput).toHaveValue("NVDA");
  });

  test("edit notes inline; persists after reload", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Seed a row.
    await page.getByLabel("Ticker").fill("MSFT");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "MSFT" })).toBeVisible();

    // Click the notes cell to start editing.
    const notesCell = page.getByText("Click to add notes").first();
    await notesCell.click();

    const textarea = page.locator("textarea").first();
    await textarea.fill("monitoring AI rumors");
    await textarea.press("Enter");

    await expect(page.getByText("monitoring AI rumors")).toBeVisible();

    // Reload and confirm persistence.
    await page.reload();
    await expect(page.getByText("monitoring AI rumors")).toBeVisible();
  });

  test("remove via modal confirm; row disappears", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Seed a row.
    await page.getByLabel("Ticker").fill("TSLA");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "TSLA" })).toBeVisible();

    await page.getByRole("button", { name: /Remove TSLA from watchlist/i }).click();
    await expect(page.getByText("Remove from watchlist?")).toBeVisible();
    await page.getByRole("button", { name: /^remove$/i }).click();

    await expect(page.getByRole("link", { name: "TSLA" })).not.toBeVisible();
  });

  test("clicking a ticker navigates to /portfolio/[ticker]", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Seed a row.
    await page.getByLabel("Ticker").fill("GOOG");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "GOOG" })).toBeVisible();

    await page.getByRole("link", { name: "GOOG" }).click();
    await expect(page).toHaveURL(/\/portfolio\/GOOG/);
  });
});
```

- [ ] **Step 2: Run the spec**

```bash
cd web && npx playwright test watchlist.spec --reporter=line 2>&1 | tail -12
```

Expected: 7 tests pass if a dev server is available. If port 3000 is occupied locally (the persistent issue across this codebase), tests will be deferred to the pre-merge workflow dispatch.

- [ ] **Step 3: Worktree discipline + commit**

```bash
git add web/tests/e2e/watchlist.spec.ts
git commit -m "test(web): Playwright e2e for /watchlist flows

Seven tests cover:
- empty state on new user
- add ticker via QuickAddForm; row appears
- duplicate add shows inline 'already on your watchlist'
- lowercase ticker auto-uppercased on input
- inline notes edit persists across reload
- remove via <dialog> modal confirm; row disappears
- click ticker navigates to /portfolio/[ticker]

Uses the same inline credentials-provider sign-in helper as the other
e2e specs (smoke.spec.ts, login.spec.ts, etc.) — no global setup."
```

---

## Phase 6 — Ship

### Task 8: PR + pre-merge dispatch + merge + smoke

**Files:** none (all the work is shipping).

- [ ] **Step 1: Push the branch**

```bash
git push --set-upstream fork feature/watchlists
```

Expected: `* [new branch] feature/watchlists -> feature/watchlists`.

- [ ] **Step 2: Open the PR**

```bash
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(watchlist): per-user watchlist as Wave 5.1 foundation" \
  --base main \
  --head feature/watchlists \
  --body "$(cat <<'EOF'
## Summary

Wave 5.1 — the first sub-project of the agentic-monitoring effort (Wave 5). Adds a per-user, single-flat, explicit watchlist that the Monitor (5.2) will later read from to decide which tickers to operate on.

## What's in this PR — 5 commits

1. \`feat(server): watchlist CRUD endpoints + watchlist_items table\` — migration (UNIQUE(user_id, ticker) + composite index), SQLAlchemy model, Pydantic schemas, FastAPI router with 4 endpoints, main.py registration, 12 new pytest tests.
2. \`feat(web): add patch<T> + del helpers + watchlist api methods\` — closes the api.ts helper gap (only had get/post before) and adds the 4 watchlist methods.
3. \`feat(web): /watchlist page (server) + QuickAddForm + WatchlistTable\` — server-rendered page + 2 client components, native \`<dialog>\` modal for remove confirmation, inline-editable notes.
4. \`feat(web): add Watchlist to nav (Bookmark icon, last item)\` — surfaces the page from anywhere.
5. \`test(web): Playwright e2e for /watchlist flows\` — 7 tests covering add / dedupe / edit-notes / remove / navigation.

## Locked decisions from the brainstorm

- Pure explicit watchlist (vs implicit-from-analysis-history) — bounds Wave 5.2's LLM cost.
- Flat single list per user (vs named lists).
- Schema: \`(id, user_id, ticker, notes, added_at)\` with UNIQUE(user_id, ticker) + (user_id, added_at DESC) index.
- Dedicated \`/watchlist\` page with new Nav item (vs section on /portfolio or modal).
- Remove confirmation: native \`<dialog>\` modal (vs toast-with-undo) — simpler v1, no new infra.
- Notes max 500 chars (Pydantic + DB enforce).
- Ticker casing: client uppercases onChange + server rejects lowercase via TICKER_RE.

## Test plan

- [x] Server: previous baseline + 12 passing
- [x] Migration up + down round-trips
- [x] \`npm run build\` clean (with NEXTAUTH_SECRET set)
- [x] 7 Playwright e2e tests (CI dispatch will exercise them)
- [ ] Pre-merge: workflow dispatch against PR branch
- [ ] Post-merge: manual browser smoke — add a ticker, edit notes, remove via modal, click ticker → /portfolio/[ticker]

## Followup queue (Wave 5.2+)

- 5.2 Monitor cron / trigger engine — reads from \`watchlist_items\`, periodically decides whether to run analyses, surfaces signals.
- "Add to watchlist" buttons on /portfolio/[ticker] and /history/[runId] (additive, optional).
- Latest-signal-per-ticker column on the watchlist table (depends on 5.2).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

Expected: PR URL printed.

- [ ] **Step 3: Pre-merge workflow dispatch**

```bash
gh workflow run deploy.yml --repo erikgunawans/TradingAgents --ref feature/watchlists
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: all 3 jobs succeed. If ghcr.io image pull fails with a transient `EOF` error (seen in PR #24), re-dispatch — known flake.

- [ ] **Step 4: Post-deploy smoke**

```bash
curl -fsS -o /dev/null -w "https://tradix.axiara.ai/login -> %{http_code}\n" https://tradix.axiara.ai/login
curl -fsS https://tradix.axiara.ai/api/auth/providers | python3 -c "import json, sys; print('providers:', list(json.load(sys.stdin).keys()))"
```

Expected: 200 + both `github` and `google` providers (PR #22 preserved).

- [ ] **Step 5: Merge**

```bash
PR_NUM=$(gh pr list --repo erikgunawans/TradingAgents --head feature/watchlists --json number --jq '.[0].number')
gh pr merge $PR_NUM --merge --repo erikgunawans/TradingAgents
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: merge succeeds, auto-deploy on main succeeds, alembic upgrade head runs the new migration during api container startup.

- [ ] **Step 6: Verify migration ran**

```bash
gcloud compute ssh tradix --zone=asia-southeast2-a --command='sudo docker logs tradingagents-api-1 2>&1 | grep -E "alembic.*d3e4f5a6b7c8|Running upgrade c2d3e4f5a6b7" | tail -5'
```

Expected: a line like `Running upgrade c2d3e4f5a6b7 -> d3e4f5a6b7c8, add_watchlist_items`.

- [ ] **Step 7: Sync local + cleanup**

```bash
git -C /Users/erikgunawansupriatna/TradingAgents checkout main && git -C /Users/erikgunawansupriatna/TradingAgents pull fork main
git -C /Users/erikgunawansupriatna/TradingAgents branch -d feature/watchlists
```

- [ ] **Step 8: Browser smoke**

Open `https://tradix.axiara.ai/watchlist` (signed in). Verify:

1. New "Watchlist" item in the nav header.
2. Empty state shows "Add a ticker above to start watching."
3. Add BBCA.JK with a note → row appears.
4. Click the notes cell → textarea appears, edit and save with Enter → updates.
5. Try to add BBCA.JK again → inline "already on your watchlist" error.
6. Click the ticker link → navigates to `/portfolio/BBCA.JK`.
7. Back on /watchlist, click the trash icon on the row → modal asks "Remove BBCA.JK from your watchlist?" → Remove confirms → row gone.

---

## Acceptance criteria

Mapping back to design §10:

- [ ] Migration creates `watchlist_items` with all 5 columns, FK + cascade, unique constraint, composite index → Task 3.
- [ ] All 4 endpoints behave per spec → Task 3 + Task 2's 12 tests.
- [ ] All endpoints scoped to current user → Task 2's `test_scoped_to_current_user`.
- [ ] `/watchlist` page renders the table + Nav + header + add form → Task 5.
- [ ] `Watchlist` appears in nav → Task 6.
- [ ] Add is optimistic, with router.refresh fallback → Task 5 (QuickAddForm).
- [ ] Duplicate shows inline error → Task 5 + Task 7's e2e.
- [ ] Notes inline-editable with save on blur or Enter → Task 5 (WatchlistTable).
- [ ] Remove opens `<dialog>` modal → Task 5 (WatchlistTable).
- [ ] Click ticker navigates to /portfolio/[ticker] → Task 5 (Link href).
- [ ] Empty state copy: "Add a ticker above to start watching." → Task 5.
- [ ] Lowercase ticker auto-uppercased on input → Task 5 (QuickAddForm onChange).
- [ ] Playwright e2e covers add + edit + remove + duplicate-error + navigation → Task 7.
- [ ] Migration up + down round-trip cleanly → Task 3 Step 7.

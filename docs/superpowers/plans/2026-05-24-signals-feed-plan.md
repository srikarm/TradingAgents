# Wave 5.3 Signals feed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the daily signals briefing — a new `/signals` page (with `Zap` nav item) that surfaces today's monitor-dispatched runs as a triaged feed: BUY/SELL/in-flight above HOLD, color-coded chips, watchlist notes inline, whole-card link to `/history/[runId]`.

**Architecture:** New `GET /signals/today` endpoint joins `runs ⨝ watchlist_items.notes` filtered by today's `trade_date` in user's TZ + `triggered_by='monitor'`, ordered server-side via a `CASE` rank. The web side adds a server-rendered `/signals` page that fetches via `Promise.all([signalsToday, me])`, then renders a client `SignalsFeed` component handling three empty-state branches plus the actionable/neutral two-group layout. No new tables; no migration.

**Tech Stack:** SQLAlchemy 2 async (with `case` expr), FastAPI, Pydantic v2, Next.js 15 App Router, lucide-react icons, Playwright, pytest, vitest.

---

## Verified before writing this plan

- **Alembic head**: `e4f5a6b7c8d9` (Wave 5.2 monitor migration). **No new migration in Wave 5.3** — the feed is a pure read endpoint over existing tables.
- **`EmptyState`** at `web/components/EmptyState.tsx` accepts `{ icon: LucideIcon, title: string, description: string, action?: ReactNode }`. Matches the design.
- **`/history/[runId]`** route exists (drill-in target ready).
- **Nav pattern** established in Waves 5.1 + 5.2 — add to alphabetized lucide import + append item to `NAV_ITEMS`.
- **`api.me()`** exists already in `web/lib/api.ts` (returns `UserOut` with `monitor_enabled` + `briefing_tz` exposed).
- **`patch<T>` + `get<T>`** helpers already in `web/lib/api.ts`. The new method uses `get<SignalListOut>`.

---

## ⚠️ Worktree discipline — mandatory pre-commit verification

The Wave 4 + Wave 5.1 + Wave 5.2 implementers all hit worktree-isolation gotchas. Same discipline applies here.

**Before EVERY commit, run all three checks:**

```bash
pwd                                                              # MUST start with `.claude/worktrees/agent-`
git rev-parse --abbrev-ref HEAD                                  # MUST be `feature/signals-feed` or `worktree-agent-*`
git -C /Users/erikgunawansupriatna/TradingAgents rev-parse main  # MUST equal the plan-commit SHA the dispatcher passed in your spawn message — unchanged
```

The dispatcher (parent session) quotes the **plan-commit SHA** in your spawn message — treat it as the only authoritative value; do NOT hardcode SHAs from this file. If any check fails, STOP and report BLOCKED. Remediation: `git fetch fork && git reset --hard <dispatcher-provided-SHA>`.

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

Expected: `Already up to date.` or fast-forward to fork/main HEAD (includes this plan doc).

- [ ] **Step 2: Create + push the branch**

```bash
git checkout -b feature/signals-feed
git push -u fork feature/signals-feed
```

Expected: `* [new branch] feature/signals-feed -> feature/signals-feed`.

---

## Phase 2 — Server: schema + router + 13 tests

### Task 2: Write failing pytest tests

**Files:**
- Create: `server/tests/test_signals_today.py`

- [ ] **Step 1: Write the spec file**

Create `server/tests/test_signals_today.py` with 13 tests. Use the inline-fixture pattern from `test_watchlist.py` (`async_client_authed`, `authed_user`) — same pattern Wave 5.2 used.

```python
"""GET /signals/today — daily monitor briefing feed."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User
from app.models.watchlist import WatchlistItem


def _today_in_tz(tz_name: str) -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(timezone.utc).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def _yesterday_in_tz(tz_name: str) -> str:
    from zoneinfo import ZoneInfo
    return (datetime.now(timezone.utc).astimezone(ZoneInfo(tz_name)) - timedelta(days=1)).strftime("%Y-%m-%d")


def _seed_run(db_session, user_id, ticker, trade_date, *, rating=None, status=RunStatus.QUEUED, triggered_by="monitor"):
    run = Run(
        id=uuid.uuid4(), user_id=user_id, ticker=ticker, trade_date=trade_date,
        status=status, final_rating=rating, results_path=f"/tmp/{ticker}",
        triggered_by=triggered_by,
    )
    db_session.add(run)
    return run


@pytest.mark.asyncio
async def test_unconfigured_user_returns_empty(async_client_authed, authed_user, db_session):
    """User with briefing_tz=None → 200, items=[], trade_date=null."""
    # authed_user fixture defaults: monitor_enabled=False, briefing_tz=None
    res = await async_client_authed.get("/signals/today")
    assert res.status_code == 200
    assert res.json() == {"items": [], "trade_date": None}


@pytest.mark.asyncio
async def test_monitor_on_no_signals_returns_empty_with_date(async_client_authed, authed_user, db_session):
    """Monitor on but no monitor runs today → 200, items=[], trade_date=<today>."""
    authed_user.monitor_enabled = True
    authed_user.briefing_tz = "Asia/Jakarta"
    authed_user.briefing_time_local = "07:00"
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["trade_date"] == _today_in_tz("Asia/Jakarta")


@pytest.mark.asyncio
async def test_single_buy_signal(async_client_authed, authed_user, db_session):
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "BBCA.JK", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "BBCA.JK"
    assert items[0]["final_rating"] == "BUY"


@pytest.mark.asyncio
async def test_ranking_buy_sell_inflight_hold(async_client_authed, authed_user, db_session):
    """4 seeded runs (HOLD, SELL, in-flight, BUY) → ordered [BUY, SELL, in-flight, HOLD]."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "HOLDX", today, rating="HOLD", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "SELLX", today, rating="SELL", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "FLIGHT", today, rating=None, status=RunStatus.RUNNING)
    _seed_run(db_session, authed_user.id, "BUYX", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    items = res.json()["items"]
    assert [i["ticker"] for i in items] == ["BUYX", "SELLX", "FLIGHT", "HOLDX"]


@pytest.mark.asyncio
async def test_failed_at_bottom(async_client_authed, authed_user, db_session):
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "BUYX", today, rating="BUY", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "FAILX", today, rating=None, status=RunStatus.FAILED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    items = res.json()["items"]
    assert [i["ticker"] for i in items] == ["BUYX", "FAILX"]


@pytest.mark.asyncio
async def test_manual_runs_filtered(async_client_authed, authed_user, db_session):
    """Manual run NOT in feed; only monitor runs."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "MONX", today, rating="BUY", status=RunStatus.SUCCEEDED, triggered_by="monitor")
    _seed_run(db_session, authed_user.id, "MANX", today, rating="BUY", status=RunStatus.SUCCEEDED, triggered_by="manual")
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert "MONX" in tickers and "MANX" not in tickers


@pytest.mark.asyncio
async def test_yesterday_filtered(async_client_authed, authed_user, db_session):
    """Yesterday's monitor run NOT in feed."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    yesterday = _yesterday_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "TODAY", today, rating="BUY", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "YEST", yesterday, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert tickers == ["TODAY"]


@pytest.mark.asyncio
async def test_other_user_signals_not_leaked(async_client_authed, authed_user, db_session):
    """Another user's monitor signal does NOT appear."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    other = User(id=uuid.uuid4(), github_id="other-monitor", monitor_enabled=True, briefing_tz="Asia/Jakarta")
    db_session.add(other)
    _seed_run(db_session, other.id, "LEAK", today, rating="BUY", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "OWN", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert tickers == ["OWN"]


@pytest.mark.asyncio
async def test_notes_joined_when_present(async_client_authed, authed_user, db_session):
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    db_session.add(WatchlistItem(
        id=uuid.uuid4(), user_id=authed_user.id, ticker="BBCA.JK", notes="tracking earnings",
    ))
    _seed_run(db_session, authed_user.id, "BBCA.JK", today, rating="BUY", status=RunStatus.SUCCEEDED)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.json()["items"][0]["notes"] == "tracking earnings"


@pytest.mark.asyncio
async def test_notes_null_when_ticker_unwatchlisted(async_client_authed, authed_user, db_session):
    """LEFT JOIN: signal exists, ticker not on watchlist → notes is null."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "ORPHAN", today, rating="BUY", status=RunStatus.SUCCEEDED)
    # NO WatchlistItem for ORPHAN
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "ORPHAN"
    assert items[0]["notes"] is None


@pytest.mark.asyncio
async def test_trade_date_reflects_user_tz(async_client_authed, authed_user, db_session):
    """trade_date in response is computed in user's TZ, not UTC."""
    authed_user.briefing_tz = "Asia/Jakarta"
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    expected = _today_in_tz("Asia/Jakarta")
    assert res.json()["trade_date"] == expected


@pytest.mark.asyncio
async def test_tz_none_returns_trade_date_null(async_client_authed, authed_user, db_session):
    """briefing_tz=None → trade_date in response is null."""
    authed_user.briefing_tz = None
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    assert res.json()["trade_date"] is None


@pytest.mark.asyncio
async def test_inflight_ordered_above_hold(async_client_authed, authed_user, db_session):
    """Explicit assertion: null final_rating sits above HOLD."""
    authed_user.briefing_tz = "Asia/Jakarta"
    today = _today_in_tz("Asia/Jakarta")
    _seed_run(db_session, authed_user.id, "HOLDX", today, rating="HOLD", status=RunStatus.SUCCEEDED)
    _seed_run(db_session, authed_user.id, "FLIGHT", today, rating=None, status=RunStatus.RUNNING)
    await db_session.commit()
    res = await async_client_authed.get("/signals/today")
    tickers = [i["ticker"] for i in res.json()["items"]]
    assert tickers == ["FLIGHT", "HOLDX"]
```

- [ ] **Step 2: Run to verify all 13 tests fail**

```bash
cd server && uv run pytest tests/test_signals_today.py -v 2>&1 | tail -25
```

Expected: 13 failures — likely `404 Not Found` since `/signals/today` doesn't exist yet, OR `ImportError` for the schema. No commit yet — combined with Task 3.

---

### Task 3: Implement schema + router + main.py registration

**Files:**
- Create: `server/app/schemas/signal.py`
- Create: `server/app/routers/signals.py`
- Modify: `server/app/main.py`

- [ ] **Step 1: Create `SignalOut` + `SignalListOut` schemas**

Create `server/app/schemas/signal.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SignalOut(BaseModel):
    run_id: UUID
    ticker: str
    trade_date: str
    status: str
    final_rating: str | None
    created_at: datetime
    completed_at: datetime | None
    notes: str | None

    model_config = ConfigDict(from_attributes=False)


class SignalListOut(BaseModel):
    items: list[SignalOut]
    trade_date: str | None
```

- [ ] **Step 2: Create the router**

Create `server/app/routers/signals.py`:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.run import Run
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.signal import SignalListOut, SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/today", response_model=SignalListOut)
async def signals_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SignalListOut:
    """Today's monitor-dispatched signals for the current user, ranked by
    actionability (BUY < SELL < in-flight < HOLD < FAILED)."""
    if not user.briefing_tz:
        return SignalListOut(items=[], trade_date=None)

    tz = ZoneInfo(user.briefing_tz)
    today_local = datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")

    rank = case(
        (Run.final_rating == "BUY", 0),
        (Run.final_rating == "SELL", 1),
        (Run.final_rating.is_(None), 2),
        (Run.final_rating == "HOLD", 3),
        (Run.status == "failed", 4),
        else_=5,
    )

    stmt = (
        select(Run, WatchlistItem.notes)
        .join(
            WatchlistItem,
            (WatchlistItem.user_id == Run.user_id)
            & (WatchlistItem.ticker == Run.ticker),
            isouter=True,
        )
        .where(
            Run.user_id == user.id,
            Run.triggered_by == "monitor",
            Run.trade_date == today_local,
        )
        .order_by(rank, Run.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    items = [
        SignalOut(
            run_id=run.id,
            ticker=run.ticker,
            trade_date=run.trade_date,
            status=run.status.value if hasattr(run.status, "value") else run.status,
            final_rating=run.final_rating,
            created_at=run.created_at,
            completed_at=run.completed_at,
            notes=notes,
        )
        for (run, notes) in rows
    ]
    return SignalListOut(items=items, trade_date=today_local)
```

- [ ] **Step 3: Register the router in main.py**

Edit `server/app/main.py`. Find the existing `from app.routers import ... as ..._router` imports and `app.include_router(..._router.router)` calls. Add:

```python
from app.routers import signals as signals_router
# ... later, after other include_router calls:
app.include_router(signals_router.router)
```

- [ ] **Step 4: Run tests + full suite**

```bash
cd server
uv run pytest tests/test_signals_today.py -v 2>&1 | tail -20
uv run pytest -q 2>&1 | tail -3
```

Expected: 13 new tests pass; full suite at 215 (prior) + 13 (new) = **228 passing**, 0 regressions.

- [ ] **Step 5: Worktree discipline + commit**

```bash
git add server/app/schemas/signal.py \
        server/app/routers/signals.py \
        server/app/main.py \
        server/tests/test_signals_today.py

git commit -m "$(cat <<'EOF'
feat(server): GET /signals/today endpoint (Wave 5.3)

Surfaces today's monitor-dispatched runs for the current user as a
ranked feed (BUY < SELL < in-flight < HOLD < FAILED) joined with
watchlist_items.notes (LEFT JOIN — signal still appears if user
has since un-watchlisted the ticker).

- schemas/signal.py: SignalOut + SignalListOut
- routers/signals.py: /signals/today endpoint with server-side CASE
  ranking and TZ-aware today computation
- main.py: registers the new router

13 new pytest tests cover unconfigured user (empty + null
trade_date), monitor-on-no-runs (empty + today's date), single BUY,
ranking order (BUY < SELL < in-flight < HOLD), FAILED at bottom,
manual runs filtered, yesterday filtered, IDOR scoping, notes-joined,
notes-null-when-unwatchlisted, trade_date reflects user TZ, tz-none,
and in-flight-above-HOLD.

No new tables, no migration — pure read endpoint.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

git push fork HEAD:feature/signals-feed
```

---

## Phase 3 — Web: api client + page + components + Nav

### Task 4: Regenerate openapi types + add api method + brand exports

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/lib/types.ts`
- Modify: `web/lib/openapi-types.ts` (regenerated)

- [ ] **Step 1: Regenerate OpenAPI types**

```bash
cd web && npm install && npm run codegen
```

Expected: `web/lib/openapi-types.ts` updates to include `SignalOut`, `SignalListOut`, `/signals/today` GET operation.

Verify:
```bash
grep -E "SignalOut|SignalListOut|signals/today" web/lib/openapi-types.ts | head -5
```

Should return ≥3 hits. If 0, the regen failed — investigate (server import or codegen script).

- [ ] **Step 2: Add brand exports to `web/lib/types.ts`**

Add alongside existing watchlist/monitor type exports:

```typescript
export type SignalOut = components["schemas"]["SignalOut"];
export type SignalListOut = components["schemas"]["SignalListOut"];
```

- [ ] **Step 3: Add api method to `web/lib/api.ts`**

Add `SignalListOut` to the type imports at the top, then add the method to the `api` object (place after `updateMonitor` so monitor-related and signal-related methods cluster):

```typescript
signalsToday: () => get<SignalListOut>("/signals/today"),
```

- [ ] **Step 4: Verify build**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -5
```

Expected: build succeeds. No `/signals` route yet (Task 5 adds the page).

- [ ] **Step 5: Worktree discipline + commit**

```bash
git add web/lib/api.ts web/lib/types.ts web/lib/openapi-types.ts
git commit -m "feat(web): add signalsToday api method + Signal types (Wave 5.3)

Reuses the get<T> helper. Regenerates openapi-types to surface
SignalOut + SignalListOut + /signals/today operation."
git push fork HEAD:feature/signals-feed
```

---

### Task 5: Create `/signals` page + SignalsFeed + SignalCard + Nav item + vitest unit tests

**Files:**
- Create: `web/app/signals/page.tsx`
- Create: `web/app/signals/SignalsFeed.tsx`
- Create: `web/app/signals/SignalCard.tsx`
- Create: `web/lib/__tests__/signal-ranking.test.ts`
- Modify: `web/components/Nav.tsx`

- [ ] **Step 1: Create the page (server component)**

Create `web/app/signals/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import PageHeader from "@/components/PageHeader";
import SignalsFeed from "./SignalsFeed";

export const metadata = { title: "Signals · TradingAgents" };

export default async function SignalsPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const [signals, me] = await Promise.all([
    api.signalsToday(),
    api.me(),
  ]);

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <PageHeader
          eyebrow="Daily briefing"
          title="Signals"
          description={
            signals.trade_date
              ? `What your watchlist looks like as of ${signals.trade_date}.`
              : "Auto-analyses of every watchlist ticker — once the daily Monitor is on."
          }
        />
        <div className="mt-6">
          <SignalsFeed
            initial={signals}
            monitorEnabled={me.monitor_enabled}
            tz={me.briefing_tz}
          />
        </div>
      </main>
    </>
  );
}
```

- [ ] **Step 2: Create `SignalsFeed` (client)**

Create `web/app/signals/SignalsFeed.tsx`:

```tsx
"use client";
import Link from "next/link";
import { Zap } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import type { SignalListOut, SignalOut } from "@/lib/types";
import SignalCard from "./SignalCard";

export function isActionable(s: SignalOut): boolean {
  return s.final_rating === "BUY" || s.final_rating === "SELL" || s.final_rating === null;
}

export default function SignalsFeed({
  initial, monitorEnabled, tz,
}: {
  initial: SignalListOut;
  monitorEnabled: boolean;
  tz: string | null;
}) {
  if (!monitorEnabled) {
    return (
      <EmptyState
        icon={Zap}
        title="Daily Monitor is off"
        description="Enable the daily Monitor on /watchlist to get a fresh signal for every ticker every morning."
        action={
          <Link
            href="/watchlist"
            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-brand/60 bg-brand/10 px-4 text-sm font-medium text-brand hover:bg-brand/15"
          >
            Go to Watchlist
          </Link>
        }
      />
    );
  }

  if (initial.items.length === 0) {
    return (
      <EmptyState
        icon={Zap}
        title={`No signals yet for ${initial.trade_date ?? "today"}`}
        description={
          tz
            ? `Waiting for the next briefing run. The Monitor fires at your configured time (${tz}).`
            : "Configure a briefing time on /watchlist."
        }
        action={
          <Link
            href="/watchlist"
            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-border/60 bg-surface/40 px-4 text-sm text-fg-muted hover:text-fg"
          >
            Manage Monitor
          </Link>
        }
      />
    );
  }

  const actionable = initial.items.filter(isActionable);
  const neutral = initial.items.filter((s) => !isActionable(s));

  return (
    <div className="space-y-6">
      {actionable.length > 0 && (
        <section aria-label="Actionable signals">
          <h2 className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            Actionable · {actionable.length}
          </h2>
          <div className="flex flex-col gap-2">
            {actionable.map((s) => (
              <SignalCard key={s.run_id} signal={s} />
            ))}
          </div>
        </section>
      )}
      {neutral.length > 0 && (
        <section aria-label="Holds">
          <h2 className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            Holding pattern · {neutral.length}
          </h2>
          <div className="flex flex-col gap-2 opacity-60">
            {neutral.map((s) => (
              <SignalCard key={s.run_id} signal={s} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create `SignalCard` (client)**

Create `web/app/signals/SignalCard.tsx`:

```tsx
"use client";
import Link from "next/link";
import { ArrowUp, ArrowDown, Minus, Loader2, Bookmark } from "lucide-react";
import type { SignalOut } from "@/lib/types";

export default function SignalCard({ signal }: { signal: SignalOut }) {
  const Icon =
    signal.final_rating === "BUY" ? ArrowUp :
    signal.final_rating === "SELL" ? ArrowDown :
    signal.final_rating === "HOLD" ? Minus :
    Loader2;

  const tone =
    signal.final_rating === "BUY"  ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" :
    signal.final_rating === "SELL" ? "text-rose-400 bg-rose-500/10 border-rose-500/30" :
    signal.final_rating === "HOLD" ? "text-fg-muted bg-surface/40 border-border/60" :
    "text-fg-muted bg-surface/40 border-border/60 animate-pulse";

  return (
    <Link
      href={`/history/${signal.run_id}`}
      className="group flex items-center gap-3 rounded-xl border border-border/60 bg-surface/40 px-4 py-3 backdrop-blur-sm transition-colors hover:border-border hover:bg-surface/70"
    >
      <div
        className={`flex h-8 w-16 shrink-0 items-center justify-center gap-1 rounded-md border ${tone} font-mono text-[11px] font-semibold uppercase`}
      >
        <Icon
          className={`h-3 w-3 ${!signal.final_rating ? "animate-spin" : ""}`}
          aria-hidden
        />
        {signal.final_rating ?? "…"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[15px] font-semibold text-fg">
            {signal.ticker}
          </span>
          <span className="font-mono text-[10px] text-fg-subtle">
            {new Date(signal.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        {signal.notes && (
          <p className="mt-0.5 truncate text-xs text-fg-muted">
            <Bookmark className="mr-1 inline h-2.5 w-2.5" aria-hidden />
            {signal.notes}
          </p>
        )}
      </div>
    </Link>
  );
}
```

- [ ] **Step 4: Add `Signals` to Nav**

Edit `web/components/Nav.tsx`. Find the existing lucide import:

```typescript
import { Activity, Bookmark, History, PieChart, PlayCircle } from "lucide-react";
```

Add `Zap` alphabetically:

```typescript
import { Activity, Bookmark, History, PieChart, PlayCircle, Zap } from "lucide-react";
```

Find the `NAV_ITEMS` array and append:

```typescript
const NAV_ITEMS = [
  { href: "/history", label: "History", icon: History },
  { href: "/live", label: "Live", icon: Activity },
  { href: "/launch", label: "Launch", icon: PlayCircle },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
  { href: "/watchlist", label: "Watchlist", icon: Bookmark },
  { href: "/signals", label: "Signals", icon: Zap },
];
```

- [ ] **Step 5: Vitest unit tests for `isActionable` + split**

Create `web/lib/__tests__/signal-ranking.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { isActionable } from "@/app/signals/SignalsFeed";
import type { SignalOut } from "@/lib/types";

function s(rating: SignalOut["final_rating"]): SignalOut {
  return {
    run_id: "00000000-0000-0000-0000-000000000000",
    ticker: "X",
    trade_date: "2026-05-24",
    status: "succeeded",
    final_rating: rating,
    created_at: "2026-05-24T00:00:00Z",
    completed_at: null,
    notes: null,
  };
}

describe("isActionable", () => {
  it("returns true for BUY, SELL, null (in-flight)", () => {
    expect(isActionable(s("BUY"))).toBe(true);
    expect(isActionable(s("SELL"))).toBe(true);
    expect(isActionable(s(null))).toBe(true);
  });

  it("returns false for HOLD", () => {
    expect(isActionable(s("HOLD"))).toBe(false);
  });
});

describe("actionable/neutral split", () => {
  it("splits a mixed list 3/1", () => {
    const items = [s("BUY"), s("SELL"), s("HOLD"), s(null)];
    const actionable = items.filter(isActionable);
    const neutral = items.filter((x) => !isActionable(x));
    expect(actionable.length).toBe(3);
    expect(neutral.length).toBe(1);
    expect(neutral[0].final_rating).toBe("HOLD");
  });
});
```

If `isActionable` isn't currently exported from `SignalsFeed.tsx`, change the export in Step 2 from `function isActionable` to `export function isActionable`. (Already shown in Step 2's code as `export function`.)

- [ ] **Step 6: Run vitest + build**

```bash
cd web
npx vitest run lib/__tests__/signal-ranking.test.ts 2>&1 | tail -10
NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -10
```

Expected: 2 vitest tests pass; build succeeds; route list includes `/signals` as `ƒ` (server-rendered on demand).

- [ ] **Step 7: Worktree discipline + commit**

```bash
git add web/app/signals/page.tsx \
        web/app/signals/SignalsFeed.tsx \
        web/app/signals/SignalCard.tsx \
        web/lib/__tests__/signal-ranking.test.ts \
        web/components/Nav.tsx

git commit -m "$(cat <<'EOF'
feat(web): /signals page + SignalsFeed + SignalCard + Nav (Wave 5.3)

- page.tsx (server component) fetches signalsToday + me in parallel,
  redirects unauthed, renders Nav + PageHeader + SignalsFeed.
- SignalsFeed (client) handles three states: monitor-off (EmptyState
  → /watchlist), no-signals-yet (EmptyState with TZ-aware copy),
  has-signals (actionable section above neutral; HOLD section at
  60% opacity).
- SignalCard (client) shows a color-coded BUY/SELL/HOLD/in-flight
  chip + ticker + created_at time + watchlist notes; the whole card
  is a Link to /history/{run_id}.
- Nav gets a 6th item ("Signals", Zap icon) after Watchlist.
- 2 vitest unit tests for isActionable + the actionable/neutral
  filter split.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

git push fork HEAD:feature/signals-feed
```

---

## Phase 4 — E2E

### Task 6: Playwright e2e for signals flow

**Files:**
- Create: `web/tests/e2e/signals.spec.ts`

- [ ] **Step 1: Write the spec**

Create `web/tests/e2e/signals.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/signals", () => {
  test("monitor-off empty state renders", async ({ page }) => {
    await signIn(page);
    // Disable monitor first (idempotent, in case previous tests left it on).
    await page.goto("/watchlist");
    const disable = page.getByRole("button", { name: /^disable$/i });
    if (await disable.isVisible().catch(() => false)) {
      await disable.click();
    }
    await page.goto("/signals");
    await expect(page.getByRole("heading", { name: /Daily Monitor is off/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /Go to Watchlist/i })).toBeVisible();
  });

  test("no-signals-yet empty state renders after enabling", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    await page.getByRole("button", { name: /^enable$/i }).click();
    await page.goto("/signals");
    await expect(page.getByRole("heading", { name: /No signals yet/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /Manage Monitor/i })).toBeVisible();
  });

  test("Signals nav item links to /signals", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: /signals/i }).click();
    await expect(page).toHaveURL(/\/signals/);
  });

  test.skip("Signal card → /history/[runId]", async ({ page }) => {
    // Requires seeded triggered_by='monitor' run; deferred to manual smoke post-merge.
  });
});
```

- [ ] **Step 2: Run (deferred to CI if no local dev server)**

```bash
cd web && npx playwright test signals.spec --reporter=line 2>&1 | tail -10
```

If `ECONNREFUSED 127.0.0.1:3000`, that's the known dev-server pattern — tests deferred to pre-merge workflow.

- [ ] **Step 3: Worktree discipline + commit**

```bash
git add web/tests/e2e/signals.spec.ts
git commit -m "$(cat <<'EOF'
test(web): Playwright e2e for /signals (Wave 5.3)

Three active tests + 1 skipped:
- monitor-off empty state renders + 'Go to Watchlist' link
- no-signals-yet empty state renders after enabling Monitor
- Signals nav item links to /signals
- (skipped) Signal card → /history/[runId] requires seeded
  triggered_by='monitor' run; covered by manual smoke

Uses the same inline credentials-provider sign-in helper as the
other e2e specs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push fork HEAD:feature/signals-feed
```

---

## Phase 5 — Ship

### Task 7: PR + pre-merge dispatch + merge + smoke

**Files:** none (git + gh CLI).

- [ ] **Step 1: Open the PR**

```bash
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(signals): daily Signals feed UI — Wave 5.3" \
  --base main \
  --head feature/signals-feed \
  --body "$(cat <<'EOF'
## Summary

Wave 5.3 — the third sub-project of the agentic-monitoring effort. Surfaces Wave 5.2's monitor-dispatched runs as a triaged daily briefing on a new `/signals` page. Actionable signals (BUY/SELL/in-flight) float above neutral (HOLD); whole-card link to `/history/[runId]` for drill-in.

## What's in this PR — 5 commits

1. \`feat(server): GET /signals/today endpoint (Wave 5.3)\` — new schemas + router + main.py registration + 13 pytest tests (ranking, IDOR, TZ, LEFT JOIN, manual filtering).
2. \`feat(web): add signalsToday api method + Signal types (Wave 5.3)\` — get<T> reuse; regenerated openapi-types.
3. \`feat(web): /signals page + SignalsFeed + SignalCard + Nav (Wave 5.3)\` — server component + 2 client components, three empty-state branches, Zap nav item, 2 vitest unit tests.
4. \`test(web): Playwright e2e for /signals (Wave 5.3)\` — 3 active + 1 skipped.

## Locked decisions from the brainstorm

- Today-only feed (strict daily briefing matching cron cadence).
- New /signals page + Nav item (Zap, 6th position).
- New GET /signals/today endpoint (joins runs ⨝ watchlist_items.notes).
- Server-side ranking via CASE expression (BUY < SELL < in-flight < HOLD < FAILED).
- Whole-card → /history/[runId] drill-in.
- Monitor runs only (manual runs stay on /history).
- No new tables, no migration.

## Test plan

- [x] Server: 13 new tests; full suite at 228 (215 prior + 13 new)
- [x] Frontend: 2 vitest unit tests for isActionable + filter split
- [x] \`npm run build\` clean (route list shows /signals as ƒ)
- [x] 4 Playwright e2e tests (3 active + 1 skipped); CI dispatch will exercise the active ones
- [ ] Pre-merge: workflow dispatch against PR branch
- [ ] Post-merge: manual browser smoke
  - /signals shows 'Monitor off' empty state when not configured
  - Enable Monitor on /watchlist; /signals shows 'No signals yet for <today>'
  - Wait for cron tick (~5min after a set briefing time); /signals shows BUY/SELL/HOLD cards
  - Click any signal card → /history/{run_id} renders the full report

## Followup queue (Wave 5.4+)

- 5.4 Notifications — email/push when a strong signal lands; closes the freshness gap that v1's no-polling design leaves open.
- Rating-change detection (today vs yesterday delta).
- Inline expansion of the Final report on the card.
- Include manual runs in the feed (toggle?).
- Read/unread state per signal.
- Realtime updates via SSE.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

Expected: PR URL printed.

- [ ] **Step 2: Pre-merge workflow dispatch**

```bash
gh workflow run deploy.yml --repo erikgunawans/TradingAgents --ref feature/signals-feed
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: build api + build web + deploy to VM all green.

- [ ] **Step 3: Post-deploy smoke**

```bash
curl -fsS -o /dev/null -w "https://tradix.axiara.ai/login -> %{http_code}\n" https://tradix.axiara.ai/login
curl -fsS -o /dev/null -w "https://tradix.axiara.ai/signals -> %{http_code} -> %{redirect_url}\n" https://tradix.axiara.ai/signals
curl -fsS https://tradix.axiara.ai/api/auth/providers | python3 -c "import json, sys; print('providers:', list(json.load(sys.stdin).keys()))"
```

Expected: /login = 200, /signals = 307 → /api/auth/signin (auth gate), providers = ['github', 'google'].

- [ ] **Step 4: Merge**

```bash
PR_NUM=$(gh pr list --repo erikgunawans/TradingAgents --head feature/signals-feed --json number --jq '.[0].number')
gh pr merge $PR_NUM --merge --repo erikgunawans/TradingAgents
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: merge succeeds, auto-deploy on main green.

- [ ] **Step 5: Sync local + cleanup**

```bash
git -C /Users/erikgunawansupriatna/TradingAgents checkout main
git -C /Users/erikgunawansupriatna/TradingAgents pull fork main
git -C /Users/erikgunawansupriatna/TradingAgents branch -d feature/signals-feed
```

- [ ] **Step 6: Browser smoke**

Open `https://tradix.axiara.ai/signals` (signed in). Verify:

1. New "Signals" item in nav (Zap icon, after Watchlist).
2. If Monitor is off → "Daily Monitor is off" empty state with "Go to Watchlist" CTA.
3. Enable Monitor on `/watchlist`. Return to `/signals` → "No signals yet for <today>" empty state with "Manage Monitor" link.
4. Set briefing time to ~5min from now in your local TZ. Wait for the cron tick.
5. Refresh `/signals`. Today's monitor runs appear as cards — actionable (BUY/SELL/in-flight) up top with color-coded chips; HOLD below at reduced opacity.
6. Click any signal card → navigates to `/history/<run_id>` showing the full TradingAgents report.
7. If you have a ticker with watchlist notes, those appear under the ticker name on the card with a Bookmark icon.

---

## Acceptance criteria

Mapping back to design §8:

- [ ] `GET /signals/today` returns `SignalListOut` matching all 13 properties from Task 2's tests.
- [ ] `/signals` page redirects unauthed users; renders 3-state UI per Task 5.
- [ ] Nav has a 6th item "Signals" (Zap icon) after Watchlist.
- [ ] Signal cards are `<Link>`s to `/history/[runId]`.
- [ ] Watchlist notes render on signal cards where present.
- [ ] BUY/SELL/in-flight render in actionable section; HOLD renders in neutral section (60% opacity).
- [ ] Cross-user IDOR test passes.
- [ ] All tests in Task 2 + Task 5 Step 5 + Task 6 pass; `/signals` route in build output as `ƒ`.
- [ ] Browser smoke from Task 7 Step 6 succeeds post-deploy.

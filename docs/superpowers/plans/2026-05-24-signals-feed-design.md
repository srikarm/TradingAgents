# Wave 5.3 — Signals feed UI: Design

**Status**: design approved, ready for implementation plan
**Date**: 2026-05-24
**Predecessor**: Wave 5.2 Monitor (merged at `819f1d7`)
**Successor**: Wave 5.4 Notifications

---

## 1. Goal

Surface today's monitor-dispatched analyses as a triaged daily briefing on a new `/signals` page. The Monitor (Wave 5.2) now produces a `Run` row tagged `triggered_by='monitor'` for every watchlist ticker for every opted-in user, every day. Wave 5.3 makes those rows visible *as signals* — ranked by actionability so the user can scan their watchlist's health in a few seconds.

The feed is intentionally **today-only** and **monitor-only**: it answers "what does the Monitor say about my watchlist *today*?", not "show me all my analyses." The full history surface is `/history`; this is the morning briefing.

## 2. Locked decisions (from the brainstorm)

| Decision | Choice | Why |
|---|---|---|
| Time scope | Today only (strict daily briefing) | Matches the cron's once-per-day shape; no scrolling stale signals; trivial query. |
| Surface | New `/signals` page + nav item (icon: `Zap`, 6th position) | First-class discoverability; clear mental separation from `/history` (all runs) and `/watchlist` (manage tickers). |
| Ranking | Server-side: BUY/SELL/in-flight above HOLD; FAILED at bottom | Lets the user scan the top for anything actionable; HOLD/FAILED are muted. |
| Drill-in | Whole card → `/history/[runId]` | Single click target per card; reuses existing run-detail page; no new infra. |
| API | New `GET /signals/today` endpoint (not extending `/runs`) | Response shape can be optimized for the feed (joined notes, pre-ordered); future feed changes don't churn the shared `/runs` surface. |
| Run scope | Monitor runs only | Cleaner "what the Monitor said." Manual runs already visible at `/history`. |

## 3. Data shape

No new tables, no migrations. This is a pure read endpoint + UI work.

**`SignalOut` Pydantic schema** (`server/app/schemas/signal.py`):

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class SignalOut(BaseModel):
    run_id: UUID
    ticker: str
    trade_date: str            # "YYYY-MM-DD" in user's TZ
    status: str                # 'queued' | 'running' | 'succeeded' | 'failed'
    final_rating: str | None   # 'BUY' | 'HOLD' | 'SELL' | None (in-flight or parser-fail)
    created_at: datetime
    completed_at: datetime | None
    notes: str | None          # from watchlist_items.notes (LEFT JOIN)

    model_config = ConfigDict(from_attributes=False)


class SignalListOut(BaseModel):
    items: list[SignalOut]
    trade_date: str | None     # "YYYY-MM-DD" in user's TZ, or null if not configured
```

`trade_date` on `SignalListOut` rides along so the frontend can render "Today's signals · 2026-05-24" without recomputing the user's local date.

## 4. Backend — `GET /signals/today`

New router file `server/app/routers/signals.py`, mounted in `main.py` via the existing `from app.routers import signals as signals_router` pattern.

### 4.1 Endpoint implementation

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
    actionability (BUY/SELL above HOLD, FAILED at bottom)."""
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

### 4.2 Ranking rationale

The `CASE` expression projects each row to an integer rank (0-5). `ORDER BY rank, created_at DESC` then produces:

- 0: BUY
- 1: SELL
- 2: in-flight (final_rating IS NULL — covers `queued` + `running` + parser-fail-on-success)
- 3: HOLD
- 4: FAILED
- 5: anything else (defensive fallback)

This is index-friendly: Postgres + SQLite both handle CASE-driven ORDER BY without table scans on `runs` (already indexed on `user_id`, `status`, `created_at`).

### 4.3 LEFT JOIN on `watchlist_items`

A user could remove a ticker from their watchlist *after* the Monitor dispatched its run that morning. The signal still exists in `runs`; we surface it (with `notes: null`). Honest: "your Monitor said this earlier today, even though you've since stopped watching."

### 4.4 Auth + scoping

Every query filters by `Run.user_id == user.id`. No IDOR risk.

## 5. Web UI

### 5.1 Nav item

Edit `web/components/Nav.tsx`:

```typescript
import { Activity, Bookmark, History, PieChart, PlayCircle, Zap } from "lucide-react";

const NAV_ITEMS = [
  { href: "/history", label: "History", icon: History },
  { href: "/live", label: "Live", icon: Activity },
  { href: "/launch", label: "Launch", icon: PlayCircle },
  { href: "/portfolio", label: "Portfolio", icon: PieChart },
  { href: "/watchlist", label: "Watchlist", icon: Bookmark },
  { href: "/signals", label: "Signals", icon: Zap },   // NEW
];
```

### 5.2 `/signals` page (server component)

`web/app/signals/page.tsx`:

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

### 5.3 `SignalsFeed` component (client)

`web/app/signals/SignalsFeed.tsx` — handles three empty-state branches plus the two-group rendering:

```tsx
"use client";
import Link from "next/link";
import { Zap } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import type { SignalListOut, SignalOut } from "@/lib/types";
import SignalCard from "./SignalCard";

function isActionable(s: SignalOut): boolean {
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

### 5.4 `SignalCard` component (client)

`web/app/signals/SignalCard.tsx` — the row UI:

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

### 5.5 API client + types

**`web/lib/api.ts`** — add one method next to existing run/watchlist methods:
```typescript
signalsToday: () => get<SignalListOut>("/signals/today"),
```

Import `SignalListOut` from `@/lib/types` alongside existing imports.

**`web/lib/types.ts`** — add brand exports after the existing `MonitorOut`/`MonitorUpdate`:
```typescript
export type SignalOut = components["schemas"]["SignalOut"];
export type SignalListOut = components["schemas"]["SignalListOut"];
```

(Codegen will pick up the new server schemas; these re-exports thread them into the rest of `web/`.)

### 5.6 No realtime / polling

The page reloads on navigation. If new signals land while the page is open, the user refreshes. Wave 5.4 (Notifications) closes the freshness gap with server-pushed alerts.

## 6. Testing strategy

### 6.1 Server pytest (`server/tests/test_signals_today.py`) — 13 tests

1. **Empty: user not configured** (`briefing_tz=None`) → `{items: [], trade_date: null}`, status 200.
2. **Empty: monitor on, no runs today** → `{items: [], trade_date: "<today>"}`.
3. **Single BUY signal**.
4. **Ranking: BUY < SELL < in-flight < HOLD** — seed 4 runs (HOLD, SELL, in-flight, BUY), assert order `[BUY, SELL, in-flight, HOLD]`.
5. **FAILED at bottom** — seed 1 BUY + 1 FAILED → order `[BUY, FAILED]`.
6. **Manual runs filtered out** — seed 1 monitor BUY + 1 manual BUY → only monitor BUY returns.
7. **Yesterday's runs filtered out** — only today's `trade_date` is included.
8. **User scoping** — another user's signals do not leak.
9. **Notes join present** — watchlist row with notes joins correctly.
10. **Notes join LEFT — ticker removed** — signal returned with `notes: null`.
11. **`trade_date` reflects user TZ** — UTC 22:00 vs WIB 05:00 next day → correct local date.
12. **TZ-less user → `trade_date: null`** in response.
13. **In-flight runs ordered above HOLD** — explicit assertion of the null-rating bucket position.

### 6.2 Web vitest unit (`web/lib/__tests__/signal-ranking.test.ts`) — 2 tests

14. `isActionable` returns true for `"BUY"`, `"SELL"`, `null`; false for `"HOLD"`.
15. Filter split: 4 inputs (BUY, SELL, HOLD, null) → actionable=3, neutral=1.

### 6.3 Web Playwright e2e (`web/tests/e2e/signals.spec.ts`) — 3 active + 1 skipped

16. **Monitor off** — fresh user, navigate to `/signals` → "Daily Monitor is off" heading + "Go to Watchlist" link.
17. **Monitor on, no signals** — set `monitor_enabled=true`+`briefing_tz` via PATCH, navigate to `/signals` → "No signals yet for ..." heading.
18. **Nav item present** — click "Signals" in nav, URL becomes `/signals`.
19. **(Skipped) Signal card → /history/[runId]** — needs seeded `triggered_by='monitor'` run; deferred to manual smoke same as Wave 5.2 e2e.

### 6.4 Manual smoke (post-deploy)

- Click "Signals" nav item → "Monitor off" empty state appears if not configured.
- Enable Monitor on `/watchlist` → `/signals` now says "No signals yet for `<today>`".
- Set briefing time to ~5min from now in local TZ; wait for cron tick.
- Reload `/signals` → actionable/neutral sections render with correct BUY/SELL/HOLD colors.
- Click a signal card → `/history/[runId]` full report renders.
- Watchlist notes appear on cards for tickers that still have notes set.

## 7. Edge cases — explicitly covered

| Scenario | Behavior |
|---|---|
| User has watchlist but Monitor off | Empty state #1: "Daily Monitor is off" + link to `/watchlist`. |
| Monitor on but cron hasn't fired today yet | Empty state #2 with TZ-aware copy. |
| Cron fired, runs still RUNNING | In-flight cards in actionable group with spinning Loader2 icon + `…` label + `animate-pulse` border. |
| User removed a ticker after the Monitor dispatched | Signal still appears (LEFT JOIN ⇒ `notes: null`). |
| `final_rating` null on a SUCCEEDED run (parser failure) | Falls into in-flight visual treatment; full investigation via `/history/[runId]`. |
| User's TZ has DST transition today | `ZoneInfo` handles correctly; `today_local` computed once per request. |
| User opens `/signals` on a day they hadn't opted in | Empty state #1 — feed reflects current state, not history. |
| User has empty watchlist + Monitor on | Empty state #2; the Monitor had nothing to dispatch. |

## 8. Acceptance criteria

- [ ] `GET /signals/today` endpoint returns `SignalListOut` with all 13 ranking + filtering + scoping properties from §6.1.
- [ ] `/signals` page renders without auth → redirects to `/api/auth/signin`; with auth → renders 3-state UI per §5.3.
- [ ] Nav has a 6th item "Signals" with `Zap` icon, position after Watchlist.
- [ ] Signal cards are `<Link>`s to `/history/[runId]`.
- [ ] Watchlist notes render inline on signal cards where present.
- [ ] BUY/SELL/in-flight render in the actionable section; HOLD renders in the neutral section (60% opacity).
- [ ] Cross-user IDOR test passes — user A cannot see user B's signals.
- [ ] All tests in §6 pass; `/signals` route in build output as `ƒ` (server-rendered on demand).
- [ ] Browser smoke from §6.4 succeeds post-deploy.

## 9. Out of scope (deferred to later waves)

- **Wave 5.4 Notifications** — push/email when a strong signal lands; closes the freshness gap that v1's no-polling design leaves open.
- **Rating-change detection** — comparing today's rating to the most-recent prior rating per ticker; surfacing only the deltas. Useful but adds a second query + per-ticker history lookup; defer.
- **Inline expansion of the Final report** — show the trader's executive summary in the card without leaving the page. Adds state + extra payload; defer.
- **Including manual runs in the feed** — could be a toggle later; cleaner to keep monitor-only for v1.
- **Per-day history browsing within `/signals`** — calendar/date picker for older briefings. Use `/history` filtered by `triggered_by='monitor'` for that today.
- **Read/unread state** — per-signal "seen" tracking, dot-indicator on the nav. Defer.
- **Realtime updates** — SSE or polling for live signal arrival. Wave 5.4 territory.

## 10. Open questions resolved during the brainstorm

| Question | Resolution |
|---|---|
| Time scope (today vs 7 days vs configurable)? | Today only — strict daily briefing matches the cron's once-per-day cadence. |
| Surface (new page vs section)? | New `/signals` page + nav item — first-class discoverability. |
| Ranking heuristic? | Server-side rank: BUY < SELL < in-flight < HOLD < FAILED. Two visual groups (actionable / neutral). |
| Drill-in target? | Whole card → `/history/[runId]`; single click target. |
| API shape — extend `/runs` or new endpoint? | New `GET /signals/today` — response shape can be optimized for the feed. |

---

**Implementation plan**: forthcoming. See `docs/superpowers/plans/2026-05-24-signals-feed-plan.md` once the plan phase runs.

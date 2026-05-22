# Wave 5.2 — Monitor: Design

**Status**: design approved, ready for implementation plan
**Date**: 2026-05-22
**Predecessor**: Wave 5.1 Watchlists (merged at `689fba1`)
**Successors**: Wave 5.3 Signals feed UI, Wave 5.4 Notifications

---

## 1. Goal

At each user's chosen briefing time, automatically dispatch a full TradingAgents analysis for every ticker on that user's watchlist. The resulting `Run` rows land in the existing `/history` feed tagged `triggered_by='monitor'` so users can distinguish auto-analyses from runs they launched themselves.

The Monitor is the **scheduling+triggering layer** on top of Wave 5.1's `watchlist_items` table. It deliberately does **not** invent a new "signal" concept — the existing `Run.final_rating` (`BUY`/`HOLD`/`SELL`) IS the signal. Wave 5.3 will build the consumer-facing feed UI around those rows.

## 2. Locked decisions (from the brainstorm)

| Decision | Choice | Why |
|---|---|---|
| Cadence | Daily, once per trading day | Predictable cost ~$5/day per 10-ticker watchlist; reuses existing `(user, ticker, trade_date)` uniqueness constraint without schema relaxation. |
| Opt-in scope | Global per-user toggle | Simplest UX; one place to turn monitoring on/off; defers per-ticker granularity to a later wave. |
| Firing time | User-configurable HH:MM in user's IANA timezone | Lets users in different markets (US/JK) pick a personally-useful briefing time; avoids per-market scheduling logic in v1. |
| Run distinction | `Run.triggered_by` enum (`'manual'` default \| `'monitor'`) | Small schema change; lets `/history` show a `Monitor` badge so users can mentally separate intentional vs autopilot runs. |
| Settings UI | Inline `MonitorSection` at top of `/watchlist` | No new pages or nav items; controls live where the user already thinks about which tickers get tracked. |
| Scheduler | arq cron (every 15 min) + due-users query | Zero new infra; existing arq pool already runs the pipeline; per-tick TZ math is cheap at our scale. |

## 3. Data model

One migration with two `ALTER`s:

```sql
ALTER TABLE users
  ADD COLUMN monitor_enabled BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN briefing_time_local VARCHAR(5),     -- "HH:MM" — e.g. "07:00"
  ADD COLUMN briefing_tz VARCHAR(64);            -- IANA — e.g. "Asia/Jakarta"

ALTER TABLE runs
  ADD COLUMN triggered_by VARCHAR(16) NOT NULL DEFAULT 'manual';
  -- Values: 'manual' | 'monitor'
```

**Constraints**:
- `briefing_time_local` and `briefing_tz` are nullable at the DB level (existing rows backfill to NULL). When `monitor_enabled = true`, both fields MUST be non-null. Enforcement at the API layer (Pydantic + endpoint validator), not via DB CHECK constraint (keeps the migration simple).
- `triggered_by` defaults to `'manual'` so existing rows backfill correctly without a data migration.

**No new tables.** Wave 5.1's `watchlist_items` is the data input; the existing `runs` table is the data output.

## 4. Architecture

### 4.1 Scheduler — arq cron tick

Register one new cron job alongside the existing arq settings:

```python
# server/app/services/monitor.py  (new file)
from arq import cron

async def monitor_tick(ctx: dict) -> dict:
    """Fires every 15 minutes. Dispatches due users' watchlists."""
    db = ctx["db_factory"]()
    async with db as session:
        now_utc = datetime.now(timezone.utc)
        due_users = await find_due_users(session, now_utc)
        results = []
        for user in due_users:
            r = await dispatch_user_watchlist(session, ctx["pool"], user, now_utc)
            results.append({"user_id": str(user.id), **r})
        return {"users_dispatched": len(results), "details": results}

# Registered in server/app/services/run_pool.py worker settings:
cron_jobs = [
    cron(monitor_tick, minute={0, 15, 30, 45}),
]
```

### 4.2 Due-users query

Each tick computes "which users have a briefing time in the last 15 minutes (UTC-rendered through their timezone)":

```python
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

async def find_due_users(
    db: AsyncSession,
    now_utc: datetime,
    window: timedelta = timedelta(minutes=15),
) -> list[User]:
    """Return users whose briefing instant falls in (now-window, now] in their TZ."""
    candidates = (await db.execute(
        select(User).where(
            User.monitor_enabled.is_(True),
            User.briefing_time_local.is_not(None),
            User.briefing_tz.is_not(None),
        )
    )).scalars().all()

    due: list[User] = []
    for u in candidates:
        try:
            tz = ZoneInfo(u.briefing_tz)
        except Exception:
            continue  # invalid tz on the row — skip (shouldn't happen post-API-validation)
        local_now = now_utc.astimezone(tz)
        local_window_start = (now_utc - window).astimezone(tz)
        hh, mm = map(int, u.briefing_time_local.split(":"))
        briefing_today = local_now.replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if local_window_start < briefing_today <= local_now:
            due.append(u)
    return due
```

**Window semantics**: a briefing scheduled for 07:00 matches a tick at 07:00-07:14 UTC-equivalent (the tick that fired at 07:00). The next tick at 07:15 sees the briefing instant outside the window, so it won't double-fire. Cron skew of a few seconds is absorbed by the 15-minute window.

### 4.3 Per-user dispatch

For each due user, load their watchlist and call the existing `dispatch_run()` with `triggered_by='monitor'`:

```python
async def dispatch_user_watchlist(
    db: AsyncSession,
    pool: _PoolProto,
    user: User,
    now_utc: datetime,
) -> dict:
    items = (await db.execute(
        select(WatchlistItem.ticker)
        .where(WatchlistItem.user_id == user.id)
    )).scalars().all()

    tz = ZoneInfo(user.briefing_tz)
    trade_date = now_utc.astimezone(tz).strftime("%Y-%m-%d")

    dispatched = 0
    skipped_dup = 0
    failed = 0
    for ticker in items:
        try:
            await dispatch_run(
                session=db, pool=pool, user_id=user.id,
                dashboard_dir=settings.dashboard_data_dir,
                body=RunCreate(ticker=ticker, trade_date=trade_date),
                triggered_by="monitor",
            )
            dispatched += 1
        except DuplicateRunningError:
            skipped_dup += 1
        except Exception:
            failed += 1
    return {"dispatched": dispatched, "skipped_dup": skipped_dup, "failed": failed}
```

`dispatch_run()` gets a new keyword arg:

```python
async def dispatch_run(
    *, session, pool, user_id, dashboard_dir, body,
    triggered_by: str = "manual",   # NEW — defaults preserve current behavior
) -> Run:
    ...
    run = Run(
        ...
        triggered_by=triggered_by,
    )
```

The existing call site in `routers/runs.py:create_run` passes nothing (defaults to `"manual"`); the monitor passes `"monitor"`. Existing duplicate-protection logic is unchanged.

### 4.4 trade_date semantics

`trade_date` is rendered in the **user's timezone** (not UTC). A user in Asia/Jakarta with a 07:00 briefing on 2026-05-22 gets a `trade_date='2026-05-22'` (their local date) — matching what the existing manual-launch UI shows them. This means a US user briefed at 07:00 EDT on 2026-05-22 and an Indonesian user briefed at 07:00 WIB on 2026-05-23 (same instant in UTC) get different `trade_date` strings — which is correct, because each one means "today" to that user.

### 4.5 Edge case behavior

| Scenario | Behavior |
|---|---|
| Cron tick missed (worker down 30+ min) | Briefing falls outside any subsequent 15-min window → user skipped for the day. **No backfill.** |
| User changes briefing time mid-day | New time governs the next tick. If today's briefing was already missed by the change, user waits till tomorrow. No double-fire. |
| DST spring-forward in user's TZ | `ZoneInfo` resolves the non-existent local clock-time to its post-transition equivalent. User briefed at the next valid instant. |
| User has empty watchlist | Dispatch loop runs zero times. No errors, no rows. |
| arq enqueue raises | The `Run` row is created QUEUED then marked FAILED (existing `dispatch_run` error handling). Loop continues to the next ticker. |
| Multiple ticks fire close together (arq replay) | Window comparison rejects re-dispatch. Idempotent. |
| Briefing in past hour due to invalid TZ | `ZoneInfo()` raises → user skipped silently (shouldn't happen post-validation). |
| User disables monitor mid-tick | Disable hits API → `monitor_enabled = false` → next tick's query filters them out. In-flight dispatches complete normally (they're already enqueued). |

## 5. API surface

### 5.1 `PATCH /me/monitor` (new)

Lives in `server/app/routers/me.py` next to the existing `GET /me`.

**Request**:
```json
{
  "enabled": true,
  "briefing_time_local": "07:00",
  "briefing_tz": "Asia/Jakarta"
}
```

**Response** (`MonitorOut`):
```json
{
  "enabled": true,
  "briefing_time_local": "07:00",
  "briefing_tz": "Asia/Jakarta",
  "next_briefing_at": "2026-05-23T00:00:00Z"
}
```

**Validation**:
- `briefing_time_local` matches `^([01]\d|2[0-3]):[0-5]\d$` (24h `HH:MM`).
- `briefing_tz` must be in `zoneinfo.available_timezones()`.
- When `enabled=true`, both time and tz MUST be non-null → otherwise 422.
- When `enabled=false`, time and tz are optional; if provided, they're persisted (so re-enabling restores prior config without re-prompting).

**`next_briefing_at`** is computed on the fly from `now_utc + (briefing_today - now if >0 else briefing_tomorrow - now)` rendered as UTC ISO-8601. The UI uses this to display the countdown.

### 5.2 `GET /me` (extended)

The existing `GET /me` response gets three additional fields:

```python
class MeOut(BaseModel):
    # ... existing fields ...
    monitor_enabled: bool
    briefing_time_local: str | None
    briefing_tz: str | None
```

The `/watchlist` page's server component already calls `GET /me` (for the auth gate); these fields ride along with no extra round-trip.

## 6. Web UI — `MonitorSection`

### 6.1 Component placement

```tsx
// web/app/watchlist/page.tsx (modified)
<PageHeader ... />
<div className="mt-6 space-y-6">
  <MonitorSection
    initial={{
      enabled: me.monitor_enabled,
      briefingTimeLocal: me.briefing_time_local,
      briefingTz: me.briefing_tz,
    }}
    tickerCount={items.length}
    tickers={items.slice(0, 3).map((i) => i.ticker)}
  />
  <QuickAddForm />
  <WatchlistTable initialItems={items} />
</div>
```

### 6.2 Visual states

**State A — monitor off (default for new users)**:
```
┌────────────────────────────────────────────────────────────────────┐
│  ◯ Daily monitor                                          [Enable] │
│  Auto-analyze your 3 tickers once a day.                           │
└────────────────────────────────────────────────────────────────────┘
```

If `tickerCount === 0`, subtitle reads: "Add tickers above, then enable to auto-analyze them daily."

**State B — monitor on**:
```
┌─────────────────────────────────────────────────────────────────────┐
│  ● Daily monitor                              Next briefing: 4h 12m │
│  ┌──────────────┬──────────────────────┬────────────────────────┐  │
│  │ Time         │ Timezone             │                        │  │
│  │ [ 07 : 00  ] │ [Asia/Jakarta     ▾] │           [ Disable ]  │  │
│  └──────────────┴──────────────────────┴────────────────────────┘  │
│  At 07:00 Asia/Jakarta each day, we analyze 3 tickers               │
│  (BBCA.JK, AAPL, BMRI.JK).                                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.3 Defaults on enable

When the user clicks **Enable** from State A:
- `briefingTimeLocal` defaults to `"07:00"`
- `briefingTz` defaults to `Intl.DateTimeFormat().resolvedOptions().timeZone` (browser-detected, e.g. `"Asia/Jakarta"`)
- The component **immediately** POSTs `PATCH /me/monitor` with these defaults (user is "on" right away — no separate Save click required), then transitions to State B with the form prefilled.

Subsequent edits in State B (time picker, tz dropdown) **auto-save** with an 800ms debounce on idle. No explicit Save button. **Disable** is a separate one-click action that POSTs `{enabled: false}` and transitions back to State A.

### 6.4 "Next briefing in X" countdown

Computed client-side from the `next_briefing_at` field returned by `GET /me` and `PATCH /me/monitor`. Recomputes every 60 seconds via `useEffect` interval. When the countdown ticks past zero, the component calls `router.refresh()` to repaint with the next day's countdown.

### 6.5 Run badge in `/history`

A small chip is added to `/history` row rendering:

```tsx
{run.triggered_by === "monitor" && (
  <span className="ml-2 inline-flex items-center gap-1 rounded-full
                   bg-brand/10 px-2 py-0.5 text-[10px] font-mono
                   uppercase tracking-wide text-brand">
    <Sparkles className="h-2.5 w-2.5" /> Monitor
  </span>
)}
```

`history/page.tsx` already receives the full `Run` row from `GET /runs`; the new `triggered_by` field rides along.

## 7. Testing strategy

### 7.1 Server pytest

**`find_due_users` unit tests** (with frozen time via `freezegun` or manual `datetime` injection):
1. User at 07:00 Asia/Jakarta, tick at 00:00 UTC (= 07:00 WIB) → due
2. Same user, tick at 00:14 UTC → due (still in 15-min window)
3. Same user, tick at 00:15 UTC → NOT due (window passed)
4. Same user, tick at 23:45 UTC (= 06:45 WIB next day) → NOT due
5. User with `monitor_enabled=false` → NOT due
6. User with `briefing_tz=null` → NOT due (incomplete config)
7. User during DST spring-forward (US/Eastern, briefing at 02:30 on the lost-hour day) → resolves via zoneinfo without crash
8. Two users, different TZs, only one due → correct subset returned

**`dispatch_user_watchlist` integration tests** (real DB session + mocked arq pool):
9. 3 watchlist tickers, no prior runs today → 3 `Run` rows created, all `triggered_by='monitor'`, status `QUEUED`
10. 3 tickers, manual run already exists for ticker[1] today → 2 new rows, `DuplicateRunningError` caught silently, counted as `skipped_dup`
11. 0 tickers → no rows, no errors
12. arq enqueue raises → run row marked `FAILED`, loop continues, `failed` counter increments

**`monitor_tick` end-to-end** (real DB + mocked pool):
13. 2 users due, 1 user not due → only the 2 due users' watchlists dispatched

**`PATCH /me/monitor` endpoint tests**:
14. Enable with valid time+tz → 200, persisted, `next_briefing_at` returned
15. Enable without time → 422
16. Enable without tz → 422
17. Enable with invalid tz string ("Not/A/Zone") → 422
18. Enable with malformed time ("25:00") → 422 (Pydantic pattern fails)
19. Disable → 200, time+tz preserved on the row (so re-enabling restores)
20. Unauthed → 401

**`GET /me`** test:
21. Three new fields present in response shape

### 7.2 Web vitest + Playwright

**vitest unit** (`web/lib/__tests__/countdown.test.ts`):
- "Next briefing in Xh Ym" formatter — 0min, 23h59m, edge of DST day

**Playwright e2e** (`web/tests/e2e/monitor.spec.ts`):
- Enable monitor from `/watchlist` → toggle visible as ON → reload → state persists
- Disable → State A again
- Change time → "Next briefing" countdown recomputes
- Open `/history` → run with `triggered_by='monitor'` shows the `Monitor` badge (seeded via test fixture)

### 7.3 Manual smoke (post-deploy)

- Log into prod, set briefing time to "5 minutes from now" in local TZ
- Wait for the cron tick to fire
- Observe new `triggered_by='monitor'` rows in `/history`
- Verify the Monitor badge renders

## 8. Acceptance criteria

Mapping back to design §2:

- [ ] Daily cadence achievable: one cron tick spawns at-most-one set of runs per user per day → §4.2 window math + §4.3 `DuplicateRunningError` handling
- [ ] Global per-user opt-in via `users.monitor_enabled` → §3
- [ ] User-configurable briefing time + IANA tz with validation → §5.1
- [ ] `Run.triggered_by` enum populated correctly for monitor-dispatched runs → §4.3
- [ ] Inline `MonitorSection` renders on `/watchlist` with toggle + time + tz + countdown → §6
- [ ] `Monitor` badge appears in `/history` for monitor-dispatched runs → §6.5
- [ ] Edge cases handled per §4.5 (missed ticks, DST, empty watchlist, in-flight disable)
- [ ] All tests in §7.1-§7.2 pass; manual smoke in §7.3 succeeds post-deploy

## 9. Out of scope (deferred to later waves)

- **Wave 5.3 (Signals feed UI)**: A dedicated "what changed today" view that aggregates today's `triggered_by='monitor'` runs across watchlists, grouped by signal strength. The Monitor lays the data; 5.3 visualizes it.
- **Wave 5.4 (Notifications)**: Email/push when a strong-signal run lands. Independent of 5.2's scheduler.
- **Per-ticker opt-in**: Add a `monitor` boolean to `watchlist_items` so users can keep a watchlist but only auto-monitor a subset.
- **Cost cap / budget guards**: Show estimated daily cost on enable; cap at $X/month with auto-disable. Currently the user-pays-OpenRouter model bounds platform risk.
- **Event-driven re-runs**: A cheap "watcher" loop that triggers a full analysis on >X% price moves or news headlines, in addition to the daily briefing.
- **"Pause for a week" button**: Adds a `paused_until` column. Useful but not v1.
- **"Run all tickers now" button**: A one-click dispatch loop accessible from `MonitorSection`. Additive; can be slotted in later.
- **Per-day briefing history view**: A page showing "your last 30 briefings" with summary stats. Subsumed by 5.3.

## 10. Open questions resolved during the brainstorm

| Question | Resolution |
|---|---|
| Cadence — real-time vs daily vs event-driven? | Daily MVP; event-driven deferred. Cost shape dictates this. |
| Opt-in granularity — global vs per-ticker vs always-on? | Global per-user. Per-ticker can layer in later as `watchlist_items.monitor`. |
| Firing time — fixed UTC vs market-aware vs user-configurable? | User-configurable. The TZ math is contained in one helper; well worth the flexibility. |
| Distinguish monitor vs manual runs? | Yes, via `Run.triggered_by`. Tiny schema cost, real UX win. |
| Settings surface — new `/settings` page vs inline vs profile dropdown? | Inline on `/watchlist`. No new pages; controls live where the user already thinks about which tickers are tracked. |
| Scheduler shape — arq cron vs polled `next_fire_at_utc` column? | arq cron + per-tick query. No DST/recompute logic; no new column. |

---

**Implementation plan**: forthcoming. See `docs/superpowers/plans/2026-05-22-monitor-plan.md` once the plan phase runs.

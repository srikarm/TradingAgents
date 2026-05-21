# Design: Real-time analysis opt-in (Wave 4 item 2)

**Date:** 2026-05-21
**Status:** Approved (design) — implementation plan to follow
**Owner:** erikgunawans
**Related:** Wave 4 item 2 (UX improvements that build on PR #22's auth UI). Item 3 (technical + price chart) is independent and will be brainstormed separately.

---

## 1. Context

Today, submitting the form at `/launch` calls `launchRunAction` in `web/app/launch/actions.ts:45`, which unconditionally calls `redirect(\`/live/${runId}\`)`. The user lands on `/live/[runId]` and sees a streaming log of the worker's progress (via the existing `LiveLogStream` polling component).

The user has flagged this as a UX problem: a TradingAgents analysis takes 5-15 minutes per run, and being parked on the live log stream the entire time is friction. Mature dashboards (Linear, GitHub Actions, Vercel) follow a "fire-and-forget" pattern — submit a task, go back to wherever you were, check back when it's done.

The user's exact phrasing was *"Real time analysis can be opted to be seen by the user to improve UX"*. The brainstorming session resolved the ambiguity around "opted to be seen" as: **let the user choose per-launch whether to watch the live stream, with fire-and-forget as the default.**

## 2. Goals

- A user submitting `/launch` can choose between watching the live log stream or going elsewhere (fire-and-forget).
- The default is fire-and-forget — the user explicitly opts IN to live view, not out of it.
- When a run is in progress and the user is NOT watching it, an ambient indicator in the nav surfaces the count of in-progress runs so the user remembers to come back.
- Clicking the indicator goes to `/history` (where the in-progress run is visible at the top).
- The existing `/live/[runId]` page, `LiveLogStream` component, and `/history` page are unchanged — the opt-in is purely about WHERE the user lands after Launch.

## 3. Non-goals

- Toast/banner notifications on run completion (deferred — could be a future feature if push-style alerts are wanted).
- Browser Notifications API / Service Worker (deferred — needs permission flow + SW infra).
- Email notifications (deferred — needs SMTP / SendGrid infra).
- User-level preference / settings page for "always watch live" (deferred — easy upgrade later if usage shows users always want one or the other).
- Per-run notification toggle (out of scope — the per-launch checkbox handles the choice that matters).
- Filtering `/history` to in-progress runs via query param (out of scope; the click-target is just `/history` for v1).
- WebSocket/SSE-based real-time count updates (out of scope; client polling every ~10s is adequate at this scale).

## 4. Architecture

Two surface changes, no schema changes, no new services:

1. **`/launch` form** gains a `Watch live` checkbox (unchecked by default). `launchRunAction` reads `formData.get("watch_live")` and redirects to `/live/{runId}` when checked, otherwise to `/history`.

2. **`Nav` component** embeds a small client-side `RunsBadge` that shows the count of in-progress runs for the current user. Polled every ~10 seconds via a thin server endpoint. Hidden when count is 0. Clicking it goes to `/history`.

```
   ┌──────────────────────────────────────────────────────────┐
   │  Nav (server component, in app/layout or per-page)       │
   │    ├─ existing links (History, Portfolio, ...)           │
   │    └─ RunsBadge (NEW, client) ─polls─► GET /runs/active/count
   │                                       (FastAPI)          │
   ├──────────────────────────────────────────────────────────┤
   │  /launch (page.tsx + actions.ts)                         │
   │    ├─ existing fields                                    │
   │    ├─ analyst selection                                  │
   │    └─ Watch live checkbox (NEW)                          │
   │            │                                             │
   │            └─►  launchRunAction reads watch_live:        │
   │                  checked  → redirect /live/{runId}       │
   │                  unchecked → redirect /history (NEW)     │
   └──────────────────────────────────────────────────────────┘
```

## 5. File structure

| File | Action | Responsibility |
|---|---|---|
| `web/app/launch/page.tsx` | modify | Add a `<label>` containing the `watch_live` checkbox between the analyst selection block and the Launch button. Inline help text explains the trade-off. |
| `web/app/launch/actions.ts` | modify | Read `formData.get("watch_live") === "on"`; redirect to `/live/{runId}` if true, else `/history`. The redirect call stays outside the try/catch (NEXT_REDIRECT preservation). |
| `web/components/Nav.tsx` | modify | Embed `<RunsBadge />` in the existing right-side nav area (next to user avatar / sign-out). One-line insertion. |
| `web/components/RunsBadge.tsx` | create | Client component. `useEffect` sets up a 10-second polling interval that calls `api.countActiveRuns()` and updates state. Renders a brand-red pill with a spinning loader icon + "N run(s)" label; returns `null` if count is 0. |
| `web/lib/api.ts` | modify | Add `countActiveRuns(): Promise<number>` that hits the new server endpoint. |
| `server/app/<runs router>.py` | modify | Add `GET /runs/active/count` endpoint that returns `{ "count": int }` filtered by current user. |
| `server/tests/test_runs_active_count.py` | create | Pytest: returns 0 for a user with no in-progress runs; returns the right count when there are mixed PENDING/RUNNING/SUCCEEDED/FAILED rows. |
| `web/tests/e2e/launch.spec.ts` | create or extend | Playwright: verify the checkbox is visible + unchecked by default. Verify both submit branches (checked → `/live/{id}`, unchecked → `/history`). Verify the RunsBadge appears when an in-progress run exists. |

The exact module path of the runs router on the server side (currently `server/app/<something>` — likely `server/app/api/runs.py` or `server/app/routers/runs.py`) is confirmed during plan-writing.

## 6. `/launch` form change (concrete)

Below the analyst selection block, above the Launch button:

```tsx
<label className="flex items-start gap-2 mt-4 text-sm text-fg-muted cursor-pointer">
  <input
    type="checkbox"
    name="watch_live"
    className="mt-0.5 h-4 w-4 rounded border-border bg-surface/40 text-brand focus:ring-brand/40"
  />
  <span>
    Watch live
    <span className="ml-2 text-xs text-fg-subtle">
      — stream the worker's log as it runs. Otherwise you land on History and can open it later.
    </span>
  </span>
</label>
```

Default state: **unchecked**. The inline help text explains the trade-off explicitly so it's not an opaque checkbox.

## 7. `launchRunAction` change

Current (line 45):

```typescript
redirect(`/live/${runId}`);
```

New:

```typescript
const watchLive = formData.get("watch_live") === "on";
redirect(watchLive ? `/live/${runId}` : "/history");
```

Two-line change. The redirect call stays outside the try/catch — `redirect()` throws `NEXT_REDIRECT`, which must not be caught.

## 8. `RunsBadge` component

```tsx
// web/components/RunsBadge.tsx
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";

const POLL_INTERVAL_MS = 10_000;

export default function RunsBadge() {
  const [count, setCount] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const n = await api.countActiveRuns();
        if (!cancelled) setCount(n);
      } catch {
        // Network blip — keep last value, retry on next tick.
      }
    };
    void tick();
    const id = setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (count === 0) return null;

  return (
    <Link
      href="/history"
      className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand/10 px-2.5 py-0.5 text-xs font-medium text-brand hover:bg-brand/15"
      aria-label={`${count} ${count === 1 ? "run" : "runs"} in progress`}
    >
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      <span>
        {count} {count === 1 ? "run" : "runs"}
      </span>
    </Link>
  );
}
```

Visual: small pill in brand-red palette with a spinning loader — visually distinct so the eye finds it when something IS happening, completely absent when nothing is.

## 9. `countActiveRuns()` API

### Server

New endpoint in the existing runs router (exact module path confirmed during plan-writing — see §11):

```python
@router.get("/runs/active/count")
async def count_active_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Count of runs for the current user that are still PENDING or RUNNING."""
    result = await db.execute(
        select(func.count())
        .select_from(Run)
        .where(Run.user_id == user.id)
        .where(Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
    )
    return {"count": result.scalar_one()}
```

Hits an indexed `user_id` + a status enum filter. Sub-millisecond on Postgres at small group scale. No DB pressure concern with 10s polling.

### Client

```typescript
// web/lib/api.ts (add to the existing `api` object)
countActiveRuns: async (): Promise<number> => {
  const data = await fetchJson<{ count: number }>("/runs/active/count");
  return data.count;
},
```

`fetchJson` is the existing helper used by all other `api.*` methods in `web/lib/api.ts`.

## 10. Testing

| Test | Location | Type |
|---|---|---|
| Server: returns 0 for user with no in-progress runs | `server/tests/test_runs_active_count.py` (new) | Unit |
| Server: returns N when N PENDING/RUNNING rows exist | same | Unit |
| Server: ignores SUCCEEDED and FAILED rows | same | Unit |
| Server: scoped to current user (other user's in-progress doesn't leak) | same | Unit |
| Web e2e: checkbox visible + unchecked by default on `/launch` | `web/tests/e2e/launch.spec.ts` (new or extend) | E2E |
| Web e2e: submit checked → lands on `/live/{id}` | same | E2E |
| Web e2e: submit unchecked → lands on `/history` | same | E2E |
| Web e2e: RunsBadge appears when in-progress run exists | same | E2E |

The RunsBadge E2E test will need a fixture or test-only API to create an in-progress run; this is doable via the existing run-create endpoint (which leaves the run in PENDING until the worker picks it up — if the worker is offline in the test env, the run stays PENDING long enough for assertion).

## 11. Open questions

1. **Exact server-side router path.** `server/app/<???>/runs.py` — confirmed during plan-writing.
2. **`Nav` component embed location.** The exact slot in `web/components/Nav.tsx` where `<RunsBadge />` goes — confirmed during plan-writing. The constraint is that it's visible on every page (the nav is on every authenticated page) and visually balanced with the existing right-side elements.
3. **Worker-offline run state.** If the worker is offline during dev, PENDING runs stay PENDING forever and the badge stays visible. Not a bug — it's accurate. But the test setup needs to be aware that submitting a real run in a dev env without a worker leaves a PENDING row.

## 12. Acceptance criteria

The implementation is done when all of these are true:

- [ ] `/launch` shows a "Watch live" checkbox below the analyst-selection block, **unchecked by default**, with inline help text.
- [ ] Submitting Launch with the checkbox **checked** → lands on `/live/{runId}` (current behavior preserved).
- [ ] Submitting Launch with the checkbox **unchecked** → lands on `/history` with the new run visible at the top.
- [ ] `Nav` shows a brand-red pill `N run(s)` whenever the signed-in user has ≥1 in-progress run, hidden when the count is 0.
- [ ] The pill updates within ~10 seconds of a run's status changing (next poll tick).
- [ ] Clicking the pill navigates to `/history`.
- [ ] Server endpoint `GET /runs/active/count` returns the correct count, scoped to the current user, ignoring SUCCEEDED/FAILED rows.
- [ ] Playwright e2e covers both checkbox branches + the badge appearance.
- [ ] No regression: `/live/[runId]` page renders identically whether reached via redirect or by clicking from `/history`.

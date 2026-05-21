# Real-Time Analysis Opt-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users choose per-launch whether to watch the live log stream (current behavior) or land on `/history` and check back later (new default), with an ambient nav-badge showing the count of in-progress runs.

**Architecture:** Two surface changes, no schema changes. `/launch` form gains a `Watch live` checkbox (unchecked by default); `launchRunAction` redirects to `/live/{runId}` when checked, otherwise to `/history`. A new `RunsBadge` client component embedded in the existing `Nav` polls a new `GET /runs/active/count` endpoint every 10 seconds and renders a brand-red pill when the signed-in user has ≥1 PENDING or RUNNING run.

**Tech Stack:** Next.js 15 server components + server actions, React client components, FastAPI + SQLAlchemy 2 async, Tailwind CSS, Playwright (E2E tests).

**Spec:** [`docs/superpowers/plans/2026-05-21-realtime-opt-in-design.md`](./2026-05-21-realtime-opt-in-design.md)

---

## Before You Start

This plan touches only files that already exist (plus 1 new component + 1 new test file). No env vars, no migrations, no cloud config.

Confirmed open questions from spec §11:

- **Server router**: `server/app/routers/runs.py` (already imports `APIRouter(prefix="/runs", ...)`).
- **Route ordering**: `/active/count` MUST register before `/{run_id}` so FastAPI doesn't match "active" as a UUID parameter.
- **Nav embed slot**: inside the existing `{githubId && (...)}` conditional in `web/components/Nav.tsx`, BEFORE the `<span>gh: …</span>` element.
- **E2E test fixture**: mock the count endpoint at the network layer with Playwright's `page.route()` to avoid worker-liveness dependency.

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

Expected: `Already up to date.` or fast-forward to the current HEAD (which includes commit `4df031e` adding the design doc).

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b feature/realtime-opt-in
```

Expected: `Switched to a new branch 'feature/realtime-opt-in'`.

---

## Phase 2 — Server: `GET /runs/active/count`

### Task 2: Write failing tests for the new endpoint

**Files:**
- Create: `server/tests/test_runs_active_count.py`

- [ ] **Step 1: Create the test file**

```python
# server/tests/test_runs_active_count.py
import uuid
from datetime import datetime, timezone

import pytest

from app.models.run import Run, RunStatus
from app.models.user import User


def _make_user(github_id: str = "111", email: str | None = None) -> User:
    return User(id=uuid.uuid4(), github_id=github_id, email=email)


def _make_run(user_id: uuid.UUID, status: RunStatus) -> Run:
    return Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker="TEST.JK",
        trade_date="2026-05-21",
        status=status,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_zero_count_when_no_runs(async_client_authed):
    """User with no runs at all → count = 0."""
    res = await async_client_authed.get("/runs/active/count")
    assert res.status_code == 200
    assert res.json() == {"count": 0}


@pytest.mark.asyncio
async def test_zero_count_when_only_terminal_runs(async_client_authed, db_session, authed_user):
    """User has SUCCEEDED + FAILED runs but no active ones → count = 0."""
    db_session.add(_make_run(authed_user.id, RunStatus.SUCCEEDED))
    db_session.add(_make_run(authed_user.id, RunStatus.FAILED))
    await db_session.flush()

    res = await async_client_authed.get("/runs/active/count")
    assert res.status_code == 200
    assert res.json() == {"count": 0}


@pytest.mark.asyncio
async def test_counts_pending_and_running(async_client_authed, db_session, authed_user):
    """Two PENDING + one RUNNING → count = 3. SUCCEEDED is ignored."""
    db_session.add(_make_run(authed_user.id, RunStatus.PENDING))
    db_session.add(_make_run(authed_user.id, RunStatus.PENDING))
    db_session.add(_make_run(authed_user.id, RunStatus.RUNNING))
    db_session.add(_make_run(authed_user.id, RunStatus.SUCCEEDED))
    await db_session.flush()

    res = await async_client_authed.get("/runs/active/count")
    assert res.status_code == 200
    assert res.json() == {"count": 3}


@pytest.mark.asyncio
async def test_scoped_to_current_user(async_client_authed, db_session, authed_user):
    """Other user's in-progress runs do NOT count toward current user's total."""
    other = _make_user(github_id="other-user-999")
    db_session.add(other)
    db_session.add(_make_run(other.id, RunStatus.RUNNING))
    db_session.add(_make_run(other.id, RunStatus.RUNNING))

    db_session.add(_make_run(authed_user.id, RunStatus.RUNNING))
    await db_session.flush()

    res = await async_client_authed.get("/runs/active/count")
    assert res.status_code == 200
    assert res.json() == {"count": 1}
```

- [ ] **Step 2: Verify the test fixtures `async_client_authed` and `authed_user` exist**

```bash
grep -rE "async_client_authed|authed_user" server/tests/conftest.py server/tests/conftest_pg.py 2>&1 | head -10
```

Expected: at least one of those fixture names is defined in `conftest.py`. If neither exists, fall back to the pattern used by existing tests like `server/tests/test_orphan_sweeper.py` — copy the auth + run-creation fixtures from there.

If the fixtures are named differently (e.g., `client_authed`, `user`), rename references in the test file to match what conftest actually provides. The TEST LOGIC stays the same; only the fixture parameter names change.

- [ ] **Step 3: Run to verify it fails**

```bash
cd server && uv run pytest tests/test_runs_active_count.py -v 2>&1 | tail -15
```

Expected: 4 tests fail with `404 Not Found` (the endpoint doesn't exist yet).

No commit (we commit together with Task 3's implementation).

---

### Task 3: Implement the `GET /runs/active/count` endpoint

**Files:**
- Modify: `server/app/routers/runs.py`

- [ ] **Step 1: Add the endpoint BEFORE the `/{run_id}` route**

Open `server/app/routers/runs.py`. The existing routes start at line 31:

```python
@router.get("", response_model=RunListOut)
...
@router.post("", status_code=status.HTTP_202_ACCEPTED)
...
@router.get("/{run_id}", response_model=RunDetailOut)   # ← This is line ~77
```

Insert the new endpoint immediately BEFORE the `@router.get("/{run_id}")` line. The ordering matters: FastAPI matches paths top-to-bottom, and `/{run_id}` is a catch-all that would otherwise match "active" as a UUID parameter.

```python
@router.get("/active/count")
async def count_active_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Count of runs for the current user that are still PENDING or RUNNING.

    Polled every 10s by web/components/RunsBadge.tsx to show the in-progress
    count in the nav. Filtered by user_id (scoped to current user) and a
    status enum filter — both columns are indexed, so this is sub-millisecond
    on Postgres at small-group scale.
    """
    result = await db.execute(
        select(func.count())
        .select_from(Run)
        .where(Run.user_id == user.id)
        .where(Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
    )
    return {"count": result.scalar_one()}
```

- [ ] **Step 2: Verify imports at the top of `routers/runs.py`**

Make sure the file has these imports (most should already be present from existing endpoints):

```python
from sqlalchemy import func, select
from app.models.run import Run, RunStatus
from app.models.user import User
from app.auth import get_current_user
from app.db import get_db
```

If `func` is missing from the `sqlalchemy` import line, add it. Run the file through `python -c "import ast; ast.parse(open('server/app/routers/runs.py').read())"` to confirm no syntax errors.

- [ ] **Step 3: Run the new tests + the full server suite**

```bash
cd server
uv run pytest tests/test_runs_active_count.py -v
uv run pytest -q
```

Expected:
- `test_runs_active_count.py`: 4 passed.
- Full suite: previous-total + 4 new tests (166 → 170 if you're on top of the auth UI work, or 159 + 4 = 163 if from main pre-auth-UI; check what your baseline actually is). No regressions.

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_runs_active_count.py server/app/routers/runs.py
git commit -m "feat(server): GET /runs/active/count endpoint for nav-badge polling

Returns {\"count\": N} for the current user's PENDING + RUNNING runs.
Filtered by user_id + status enum — both indexed — so sub-millisecond
even when polled every 10s.

Route placement: BEFORE @router.get(\"/{run_id}\") so FastAPI doesn't
match \"active\" as a UUID path parameter.

Tests cover: zero count, terminal-only-runs zero count, mixed PENDING/
RUNNING/SUCCEEDED, user-scoping (other user's in-progress doesn't leak)."
```

---

## Phase 3 — Web: API client + RunsBadge component

### Task 4: Add `countActiveRuns()` to the API client

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add the method to the `api` object**

Open `web/lib/api.ts` and find the `api` object definition (around line 81). Add `countActiveRuns` to the object literal:

```typescript
export const api = {
  me: () => get<UserOut>("/me"),
  listRuns: (ticker?: string) =>
    get<RunListOut>(ticker ? `/runs?ticker=${encodeURIComponent(ticker)}` : "/runs"),
  getRun: (id: string) => get<RunDetailOut>(`/runs/${id}`),
  createRun: (body: RunCreate) => post<{ run_id: string }>("/runs", body),
  tailRun: (id: string, since: number) =>
    get<RunTailOut>(`/runs/${id}/tail?since=${since}`),
  countActiveRuns: () =>
    get<{ count: number }>("/runs/active/count").then((d) => d.count),
  portfolioSummary: () => get<PortfolioSummaryOut>("/portfolio/summary"),
  portfolioCurve: () => get<PortfolioCurveOut>("/portfolio/curve"),
  portfolioTicker: (ticker: string) =>
    get<TickerDetailOut>(`/portfolio/ticker/${encodeURIComponent(ticker)}`),
};
```

Place `countActiveRuns` between `tailRun` and `portfolioSummary` to keep run-related methods grouped.

- [ ] **Step 2: Verify TypeScript builds**

```bash
cd web && npm run build 2>&1 | tail -10
```

Expected: build succeeds, no type errors.

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "feat(web): add api.countActiveRuns() helper

Wraps GET /runs/active/count and returns just the count number rather
than the {count} envelope so consumers don't unwrap repeatedly."
```

---

### Task 5: Create the `RunsBadge` client component

**Files:**
- Create: `web/components/RunsBadge.tsx`

- [ ] **Step 1: Write the component**

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
        // Network blip or 401 (signed-out tab). Keep last value;
        // next tick will retry. The badge will simply stay stale
        // until network recovers.
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
      className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand/10 px-2.5 py-0.5 text-xs font-medium text-brand transition-colors hover:bg-brand/15"
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

- [ ] **Step 2: Verify it compiles**

```bash
cd web && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add web/components/RunsBadge.tsx
git commit -m "feat(web): add RunsBadge client component

Polls api.countActiveRuns() every 10s. Renders a brand-red pill with a
spinning loader + 'N run(s)' label when count > 0; returns null when
count is 0 (invisible to users with no in-progress work).

The link target is /history — clicking the badge lands you where the
in-progress runs are visible at the top of the list."
```

---

### Task 6: Embed `RunsBadge` in `Nav`

**Files:**
- Modify: `web/components/Nav.tsx`

- [ ] **Step 1: Import the badge + insert it in the right-side slot**

Open `web/components/Nav.tsx`. Add the import at the top:

```typescript
import RunsBadge from "@/components/RunsBadge";
```

Find the existing `{githubId && (...)` block (around line 65-77) — it wraps the user's GitHub ID label + Sign-out button. Insert `<RunsBadge />` as the FIRST child of the wrapping `<div className="flex items-center gap-3 text-[12px]">`:

```tsx
{githubId && (
  <div className="flex items-center gap-3 text-[12px]">
    <RunsBadge />
    <span className="hidden text-fg-subtle sm:inline">
      <span className="text-fg-subtle">gh:</span>
      <span className="font-mono text-fg-muted">{githubId}</span>
    </span>
    <button
      type="button"
      onClick={() => signOut({ callbackUrl: "/" })}
      className="text-fg-subtle transition-colors hover:text-fg"
    >
      Sign out
    </button>
  </div>
)}
```

The `gap-3` on the parent div spaces the badge naturally from the `gh:` label.

- [ ] **Step 2: Verify the build + visual smoke**

```bash
cd web && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

Optional visual smoke (dev server):
```bash
cd web && npm run dev &
DEV_PID=$!
sleep 5
# In a browser: sign in, then visit any authenticated page.
# Expected: no badge visible (count is 0 in a fresh DB).
kill $DEV_PID 2>/dev/null
```

- [ ] **Step 3: Commit**

```bash
git add web/components/Nav.tsx
git commit -m "feat(web): embed RunsBadge in Nav header

Sits between the main nav links and the user/sign-out area, inside the
existing authenticated-user conditional block. Hidden when count is 0,
so the nav looks unchanged for users with no in-progress work."
```

---

## Phase 4 — `/launch` form + action

### Task 7: Add the `Watch live` checkbox to `/launch`

**Files:**
- Modify: `web/app/launch/page.tsx`

- [ ] **Step 1: Find the existing form structure**

The launch page renders a form (with ticker input, trade date input, analyst selection, Launch button). The checkbox goes between the analyst selection block and the Launch button. Locate the analyst-selection section by searching for `name="analysts"` in `web/app/launch/page.tsx`.

- [ ] **Step 2: Add the checkbox label**

Insert this block immediately AFTER the analyst-selection block, BEFORE the Launch submit button:

```tsx
<label className="mt-4 flex items-start gap-2 text-sm text-fg-muted cursor-pointer">
  <input
    type="checkbox"
    name="watch_live"
    className="mt-0.5 h-4 w-4 rounded border-border bg-surface/40 text-brand focus:ring-2 focus:ring-brand/40"
  />
  <span>
    Watch live
    <span className="ml-2 text-xs text-fg-subtle">
      — stream the worker's log as it runs. Otherwise you land on History and can open it later.
    </span>
  </span>
</label>
```

Note: NOT `defaultChecked` and NOT `checked` — the checkbox defaults to unchecked, which is what we want.

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

No commit yet — combined with Task 8.

---

### Task 8: Update `launchRunAction` to read the checkbox + switch redirect

**Files:**
- Modify: `web/app/launch/actions.ts`

- [ ] **Step 1: Change the redirect line**

Open `web/app/launch/actions.ts`. The current line 45:

```typescript
redirect(`/live/${runId}`);
```

Replace with:

```typescript
const watchLive = formData.get("watch_live") === "on";
redirect(watchLive ? `/live/${runId}` : "/history");
```

- [ ] **Step 2: Verify the build**

```bash
cd web && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Step 3: Manual smoke** (optional but recommended)

```bash
cd web && npm run dev &
DEV_PID=$!
sleep 5
# In a browser:
# 1. Visit /launch (signed in).
# 2. Fill the form, leave "Watch live" UNCHECKED, click Launch.
#    Expected: lands on /history with the new run at the top.
# 3. Visit /launch again. Fill the form, CHECK "Watch live", click Launch.
#    Expected: lands on /live/{runId}.
kill $DEV_PID 2>/dev/null
```

- [ ] **Step 4: Commit** (covers both Task 7 + Task 8 — coupled change)

```bash
git add web/app/launch/page.tsx web/app/launch/actions.ts
git commit -m "feat(web): /launch 'Watch live' opt-in checkbox

Add a checkbox below the analyst-selection block on the launch form,
unchecked by default. launchRunAction reads formData.get('watch_live')
and redirects to /live/{runId} when checked (current behavior), or
to /history otherwise.

Default = unchecked / fire-and-forget per the design decision: after a
few runs the live log is more noise than signal, and users who want it
can opt in per launch. The /live page remains reachable from /history
at any point during the run."
```

---

## Phase 5 — Playwright E2E

### Task 9: Add E2E tests for the opt-in flow + badge

**Files:**
- Create: `web/tests/e2e/launch-opt-in.spec.ts`

- [ ] **Step 1: Write the spec file**

```typescript
// web/tests/e2e/launch-opt-in.spec.ts
import { test, expect } from "@playwright/test";

test.describe("launch opt-in", () => {
  test("Watch live checkbox is unchecked by default", async ({ page }) => {
    await page.goto("/launch");
    const checkbox = page.getByRole("checkbox", { name: /Watch live/i });
    await expect(checkbox).toBeVisible();
    await expect(checkbox).not.toBeChecked();
  });

  test("submit with checkbox checked lands on /live/{id}", async ({ page }) => {
    await page.goto("/launch");
    await page.getByLabel(/Ticker/i).fill("BBCA.JK");
    await page.getByLabel(/Trade date/i).fill("2026-05-21");
    await page.getByRole("checkbox", { name: /Watch live/i }).check();
    await page.getByRole("button", { name: /Launch/i }).click();
    await expect(page).toHaveURL(/\/live\/[a-f0-9-]+/);
  });

  test("submit with checkbox unchecked lands on /history", async ({ page }) => {
    await page.goto("/launch");
    await page.getByLabel(/Ticker/i).fill("BMRI.JK");
    await page.getByLabel(/Trade date/i).fill("2026-05-21");
    // Leave checkbox unchecked.
    await page.getByRole("button", { name: /Launch/i }).click();
    await expect(page).toHaveURL(/\/history(\?|$)/);
  });
});

test.describe("RunsBadge in nav", () => {
  test("hidden when no in-progress runs", async ({ page }) => {
    // Mock the count endpoint at the network layer to avoid worker dependency.
    await page.route("**/runs/active/count", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ count: 0 }) })
    );
    await page.goto("/history");
    // The badge link is hidden when count === 0 (returns null).
    await expect(page.getByRole("link", { name: /run.*in progress/i })).toHaveCount(0);
  });

  test("visible with correct count + plural label", async ({ page }) => {
    await page.route("**/runs/active/count", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ count: 3 }) })
    );
    await page.goto("/history");
    const badge = page.getByRole("link", { name: /3 runs in progress/i });
    await expect(badge).toBeVisible();
    await expect(badge).toHaveAttribute("href", "/history");
    await expect(badge).toContainText("3 runs");
  });

  test("singular label when count is 1", async ({ page }) => {
    await page.route("**/runs/active/count", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ count: 1 }) })
    );
    await page.goto("/history");
    const badge = page.getByRole("link", { name: /1 run in progress/i });
    await expect(badge).toContainText("1 run");
  });
});
```

- [ ] **Step 2: Run the spec**

```bash
cd web && npx playwright test launch-opt-in.spec --reporter=line 2>&1 | tail -10
```

Expected: 6 tests pass.

> **Note**: If the existing Playwright auth setup uses a credentials provider in test mode (E2E_TEST_MODE=1), the tests will need authentication. Check `web/playwright.config.ts` for any `globalSetup` or `storageState` patterns — replicate the same auth bootstrap that `web/tests/e2e/smoke.spec.ts` uses (it already runs as authenticated; copy its pattern).

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/launch-opt-in.spec.ts
git commit -m "test(web): Playwright e2e for opt-in checkbox + RunsBadge

Six tests:
- Watch live checkbox visible + unchecked by default on /launch
- Submit checked → URL matches /live/{uuid}
- Submit unchecked → URL matches /history
- RunsBadge hidden when count=0 (page.route mock)
- RunsBadge visible with '3 runs' plural label when count=3
- RunsBadge shows '1 run' singular when count=1

Count endpoint is mocked at the network layer (page.route) so the
tests don't depend on worker liveness or real PENDING run state."
```

---

## Phase 6 — Ship

### Task 10: Push the branch + open PR

**Files:** none (git only).

- [ ] **Step 1: Push**

```bash
git push --set-upstream fork feature/realtime-opt-in
```

Expected: `* [new branch] feature/realtime-opt-in -> feature/realtime-opt-in`.

- [ ] **Step 2: Open the PR**

```bash
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(launch): real-time analysis opt-in checkbox + RunsBadge" \
  --base main \
  --head feature/realtime-opt-in \
  --body "$(cat <<'EOF'
## Summary

Wave 4 item 2. Adds a per-launch \"Watch live\" checkbox so users opt IN to the live log stream after launching a run, with a small nav badge showing in-progress run count for ambient awareness.

Default behavior changes: submitting Launch with the checkbox UNCHECKED (default) now redirects to \`/history\` instead of \`/live/{runId}\`. The /live page is unchanged — still reachable from /history at any point during the run.

Locked decisions from the brainstorm:
- Per-launch checkbox on the form (no schema changes, no settings page)
- Default = unchecked / fire-and-forget
- Nav badge polling every 10s for ambient awareness

## What's in this PR — 6 commits

**Server:**
- New \`GET /runs/active/count\` endpoint in \`server/app/routers/runs.py\`, registered BEFORE \`/{run_id}\` to avoid UUID-param matching. Returns count of PENDING + RUNNING runs scoped to current user.
- 4 new pytest tests covering zero-count, terminal-only-zero, mixed-status, and user-scoping.

**Web:**
- \`api.countActiveRuns()\` wrapping the new endpoint.
- \`RunsBadge\` client component (brand-red pill with spinning loader, hidden when count=0).
- Nav embed inside the existing authenticated-user conditional block.
- \`/launch\` form gains a \"Watch live\" checkbox with inline help copy.
- \`launchRunAction\` reads \`formData.get('watch_live')\` and redirects to /live/{id} if checked, otherwise /history.

**Tests:**
- 6 new Playwright e2e tests covering both checkbox branches + badge visibility/copy with count=0/1/3 (network-mocked via page.route, no worker dependency).

## Test plan

- [x] Server: previous-total + 4 new tests passing
- [x] \`npm run build\` clean
- [x] Playwright: 6 new e2e tests passing
- [ ] Pre-merge: dispatch workflow against PR branch (same pattern as PRs #21/#22) — verify deploy + smoke
- [ ] Post-merge: manual smoke — submit a run with checkbox UNCHECKED, verify landing on /history with the new run row; submit with checkbox CHECKED, verify landing on /live/{id}; observe nav badge populates within ~10s

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

No commit.

---

### Task 11: Pre-merge validation + merge + auto-deploy smoke

**Files:** none.

- [ ] **Step 1: Pre-merge dispatch (same pattern as PRs #21/#22)**

```bash
PR_NUM=$(gh pr list --repo erikgunawans/TradingAgents --head feature/realtime-opt-in --json number --jq '.[0].number')
gh workflow run deploy.yml --repo erikgunawans/TradingAgents --ref feature/realtime-opt-in
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: all 3 jobs succeed. The new endpoint is reachable; `curl -fsS -o /dev/null -w "%{http_code}\n" https://tradix.axiara.ai/api/runs/active/count` returns 200 if you have a valid bearer token, or 401 unauthenticated (both indicate the route is wired).

- [ ] **Step 2: Merge the PR**

```bash
gh pr merge $PR_NUM --merge --repo erikgunawans/TradingAgents
```

- [ ] **Step 3: Watch the auto-deploy**

```bash
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: success.

- [ ] **Step 4: Post-merge manual smoke** (browser, signed in)

1. Visit `https://tradix.axiara.ai/launch`.
2. Verify the "Watch live" checkbox is present and UNCHECKED by default.
3. Fill `Ticker=BBCA.JK`, `Trade date=2026-05-21`, leave checkbox unchecked, click Launch.
4. **Expected**: land on `/history` with the new BBCA.JK row at the top, showing status PENDING or RUNNING.
5. Within ~10 seconds: the nav header shows a brand-red `1 run` pill on the right side.
6. Visit `/launch` again, fill the form (different ticker), CHECK the "Watch live" checkbox, click Launch.
7. **Expected**: land on `/live/{runId}` with the live log streaming.
8. Wait for both runs to complete (or fail). The nav badge should disappear within ~10s of the last in-progress run reaching SUCCEEDED/FAILED.

- [ ] **Step 5: Sync local main + cleanup feature branch**

```bash
git checkout main && git pull fork main
git branch -d feature/realtime-opt-in
```

Expected: local main fast-forwards past the merge commit.

---

## Acceptance criteria

Mapping back to design §12:

- [ ] **§12.1** `/launch` shows "Watch live" checkbox below analyst block, unchecked by default → Tasks 7 + 9 (e2e).
- [ ] **§12.2** Submit checked → `/live/{runId}` → Task 8 + Task 9 (e2e) + Task 11 step 4.
- [ ] **§12.3** Submit unchecked → `/history` with new run at top → Task 8 + Task 9 (e2e) + Task 11 step 4.
- [ ] **§12.4** Nav shows brand-red `N run(s)` pill when ≥1 in-progress run, hidden otherwise → Tasks 5 + 6 + Task 9 (e2e).
- [ ] **§12.5** Pill updates within ~10s → Task 5 (POLL_INTERVAL_MS=10000) + Task 11 step 4 (manual observation).
- [ ] **§12.6** Clicking pill → `/history` → Task 5 (`href="/history"`) + Task 9 (e2e `toHaveAttribute("href", "/history")`).
- [ ] **§12.7** `GET /runs/active/count` returns correct count scoped to current user → Task 2 (4 pytest tests) + Task 3 (impl).
- [ ] **§12.8** Playwright e2e covers both checkbox branches + badge appearance → Task 9.
- [ ] **§12.9** No regression — `/live/[runId]` renders identically → Manual verification, Task 11 step 4.

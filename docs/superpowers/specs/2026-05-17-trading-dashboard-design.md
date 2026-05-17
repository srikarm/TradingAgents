# TradingAgents Dashboard — Design

**Status**: Approved (brainstorming)
**Date**: 2026-05-17
**Owner**: erikgunawans

## 1. Purpose

A web dashboard for the TradingAgents multi-agent LLM trading framework that exposes three lenses over the existing system, all behind SSO with per-user data isolation:

1. **History** — browse past runs by ticker/date, read the full analyst → research → trader → risk → final-decision report set.
2. **Live monitor** — watch an in-progress run, with the agent message/tool log streaming via HTTP polling.
3. **Portfolio** — aggregate across all of a user's resolved decisions: cumulative P&L curve, win rate, Sharpe, max drawdown, plus a per-ticker price chart with decision pins overlaid.

Users can also **launch new runs** from the dashboard (ticker, date, analyst selection, LLM config). Launches enqueue an out-of-process worker; the live monitor reads from the worker's on-disk `message_tool.log` rather than wiring into LangGraph callbacks.

## 2. Constraints / Decisions Locked In

| Decision | Choice | Why |
|---|---|---|
| Scope | All-in-one (history + live + portfolio) | User wants one app, not three |
| Deployment | Multi-user, deployed (Docker / cloud) | Real SaaS shape |
| Interactivity | Launch runs from UI + file-tail live monitor | No websockets, no LangGraph callback wiring |
| Auth | SSO only — GitHub OAuth (Google deferred) | NextAuth.js handles it cleanly |
| Data isolation | Per-user namespace for runs + memory log | Each user sees only their own data |
| Portfolio depth | Full P&L (cumulative curve, win rate, Sharpe, max DD) + per-ticker chart with decision pins | Highest-fidelity option chosen |
| Backend | FastAPI, co-located with `tradingagents/` package | Direct in-process import of `TradingAgentsGraph` |
| Frontend | Next.js (App Router) + TypeScript + NextAuth + Recharts | True SPA, NextAuth's GitHub OAuth is well-trodden |
| Job queue | arq (async Redis-backed) | Async-native, simpler than Celery |
| Storage | Postgres for users/runs/memory mirror; disk for markdown reports | Disk remains source of truth, Postgres is a query cache |

## 3. Architecture

```
┌──────────────────┐   HTTPS    ┌──────────────────────┐
│  Next.js (web)   │ ─────────▶ │  FastAPI (api)       │
│  · App Router    │  JWT in    │  · /runs, /reports,  │
│  · NextAuth.js   │   header   │    /portfolio, /me   │
│  · Recharts      │            │  · verifies JWT      │
└──────┬───────────┘            └──────┬───────────────┘
       │                               │
       │ NextAuth login flow           │ enqueue
       ▼                               ▼
   ┌────────────┐                ┌────────────┐
   │  GitHub    │                │  Redis +   │
   │  OAuth     │                │  arq queue │
   └────────────┘                └─────┬──────┘
                                       │ dispatches
                                       ▼
                                ┌────────────────┐
                                │  arq worker    │
                                │  · imports     │
                                │    TradingAgents│
                                │    Graph       │
                                │  · writes to   │
                                │    disk        │
                                └──────┬─────────┘
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
       ┌─────────────────┐                          ┌────────────────┐
       │ Postgres        │                          │ Filesystem     │
       │ · users         │                          │ results_dir/   │
       │ · runs metadata │                          │  <user_id>/    │
       │ · memory entries│                          │   <ticker>/    │
       │   (mirrored     │                          │    <date>/     │
       │    from log)    │                          │     reports/   │
       └─────────────────┘                          │     message_   │
                                                    │     tool.log   │
                                                    └────────────────┘
```

**Key architectural decisions:**

- **Two-service split**: Next.js owns auth + UI; FastAPI owns trading-system integration. Frontend never imports `tradingagents.*` — that boundary is API-only.
- **NextAuth mints a JWT** (HS256, signed with `NEXTAUTH_SECRET`); FastAPI verifies the signature on every request via middleware. FastAPI has no auth library of its own. `NEXTAUTH_SECRET` is the only shared secret between services.
- **Job execution out-of-process** via arq workers. The web API never blocks on `propagate()`. Worker writes reports to disk and metadata to Postgres as it runs.
- **Live monitor = file-tail polling.** Frontend polls `/api/runs/{id}/tail?since=<offset>` every 2s; FastAPI seeks the worker's `message_tool.log` and returns appended bytes. No websockets, no LangGraph callback integration.
- **Memory log stays on disk** in the existing markdown format, namespaced per user: `memory/<user_id>/trading_memory.md`. Postgres mirrors parsed entries for fast portfolio aggregation. Disk remains source of truth so the existing CLI workflow keeps working.
- **Per-user filesystem isolation**: `results_dir` becomes `~/.tradingagents/dashboard/users/<user_id>/...`. Every path access goes through a `user_root` helper that prefixes the user namespace and rejects traversal — never trusts route params for path construction.

## 4. Components

### 4.1 Frontend (Next.js, App Router, TypeScript)

```
web/
  app/
    layout.tsx                  # shell + nav, NextAuth SessionProvider
    page.tsx                    # landing → redirects to /history if signed in
    auth/[...nextauth]/route.ts # NextAuth GitHub OAuth handler
    history/
      page.tsx                  # list of past runs (filter: ticker, date, rating)
      [runId]/page.tsx          # single run: tabs for Analysts/Research/Trading/Risk
    live/
      page.tsx                  # active run monitor (polls tail endpoint)
      [runId]/page.tsx          # specific run live view
    portfolio/
      page.tsx                  # P&L curve, win rate, Sharpe, max DD
      [ticker]/page.tsx         # per-ticker drill-down with decision pins
    launch/
      page.tsx                  # form: ticker, date, analysts, model config
  components/
    RunCard.tsx, RatingBadge.tsx, AnalystReport.tsx, LiveLogStream.tsx,
    PnLChart.tsx, TickerPriceChart.tsx, DecisionTimeline.tsx
  lib/
    api.ts                      # typed fetch client → FastAPI (JWT injection)
    types.ts                    # types mirroring FastAPI Pydantic schemas
    auth.ts                     # NextAuth options + JWT signing
```

- **No global state library** — TanStack Query for server cache + URL params for filters.
- **Charts**: Recharts for P&L curve + per-ticker price chart. If we hit a wall (e.g., need crosshair tooltips synced across charts), swap to Plotly.
- **Live log component**: `useEffect` polling loop with `AbortController` cleanup on unmount, exponential backoff (2s → 4s → 8s → 16s capped) on 5xx, immediate stop when run reaches a terminal status.

### 4.2 Backend (FastAPI)

```
server/
  app/
    main.py                  # FastAPI() + middleware mount
    config.py                # pydantic-settings, loads .env
    auth.py                  # JWT verification middleware, get_current_user dep
    db.py                    # SQLAlchemy async engine + session factory
    models/
      user.py                # User(id, github_id, email, created_at)
      run.py                 # Run(id, user_id, ticker, trade_date, status,
                             #     created_at, last_heartbeat_at, completed_at,
                             #     final_rating, results_path,
                             #     error_summary, error_detail)
      memory_entry.py        # MemoryEntry(id, user_id, ticker, trade_date,
                             #             rating, status, realized_return)
    routers/
      runs.py                # POST /runs, GET /runs, GET /runs/{id},
                             # GET /runs/{id}/tail, GET /runs/{id}/report/{section}
      portfolio.py           # GET /portfolio/summary, /portfolio/curve,
                             # /portfolio/ticker/{ticker}
      memory.py              # GET /memory/entries, PATCH /memory/entries/{id}
      me.py                  # GET /me, GET /me/config
    services/
      user_root.py           # joins paths under per-user namespace; rejects ..
      run_dispatcher.py      # enqueues arq job, creates Run row
      log_tailer.py          # safe byte-offset read of message_tool.log
      memory_mirror.py       # parses trading_memory.md → Postgres on changes
      portfolio_calc.py      # rating→size mapping, cumulative P&L, Sharpe, DD
    workers/
      tasks.py               # arq task: run_propagate(user_id, run_id, ...)
                             # also: orphan_sweeper cron task
```

### 4.3 Worker (arq)

- Primary task: `run_propagate(user_id, run_id, ticker, trade_date, analysts, llm_config)`.
- Builds `TradingAgentsGraph` with `results_dir` and `memory_log_path` rooted at the user's namespace, calls `.propagate()`.
- Updates `Run.status` at three checkpoints: `queued → running → succeeded|failed`.
- On success: triggers `memory_mirror.sync(user_id)` to refresh Postgres.
- **LLM API keys come from env vars on the worker only** — never sent from the frontend, never stored per-user in v1. Per-user keys are an explicit v2 concern.
- **Heartbeat**: while a run is in flight, the worker updates `Run.last_heartbeat_at` every 30s via a small `asyncio.create_task` heartbeat loop that runs alongside `propagate()`. The loop stops cleanly when the task completes (success or failure).
- **Cron task `orphan_sweeper`** runs every 5 minutes, marks any `running` Run with `last_heartbeat_at` older than 10 min as `failed` with `error_summary='worker_lost'`.

### 4.4 Shared / cross-cutting

- **`user_root` helper** — single source of truth for path joins. Every storage access flows through it. Rejects any segment containing `..`, absolute paths, or NUL bytes. Validates `user_id` matches `^[a-f0-9-]{36}$` (UUID format). Treated as a security primitive with its own test file.
- **Memory mirror** — one-way (disk → Postgres). If a user edits `trading_memory.md` by hand (existing CLI workflow), the next worker run picks it up. Postgres is a cache, not authoritative.
- **Rating → size mapping** for portfolio P&L: `{Buy: +1.0, Overweight: +0.5, Hold: 0, Underweight: -0.5, Sell: -1.0}`. Lives as a constant in `portfolio_calc.py`. User-tunable in v2.

## 5. Data Flow

### 5.1 Login

```
User → /auth/signin → NextAuth → GitHub OAuth consent → callback
       → NextAuth verifies, calls jwt() callback → mints JWT
         payload: { sub: github_id, email, iat, exp }
         signed: HS256 with NEXTAUTH_SECRET (shared with FastAPI)
       → stored in HTTP-only session cookie
       → first API call: GET /api/me with Authorization: Bearer <jwt>
       → FastAPI auth.py verifies signature, decodes payload
       → looks up User by github_id; if missing, inserts row (idempotent upsert)
       → returns { user_id, email, created_at }
```

- JWT lifetime: 7 days. NextAuth handles silent refresh via the `jwt()` callback.
- No server-side refresh tokens.
- `NEXTAUTH_SECRET` rotation = env-var change + restart of both services.

### 5.2 Launch + monitor a run

```
─ Submit ─────────────────────────────────────────────────────────────
Frontend (Launch page)
  → user fills ticker=NVDA, date=2024-05-10, analysts=[market,news], ...
  → POST /api/runs  { ticker, trade_date, analysts, llm_config }
FastAPI runs.create()
  → get_current_user → user_id
  → user_root.results_dir(user_id, ticker, trade_date)
    → /var/lib/trading/users/<user_id>/NVDA/2024-05-10
  → INSERT Run(..., status='queued', results_path=<above>)
  → arq.enqueue("run_propagate", run_id, ...)
  → 202 { run_id }

─ Worker ─────────────────────────────────────────────────────────────
arq tasks.run_propagate(run_id)
  → loads Run row, marks status='running'
  → builds config dict with per-user results_dir + memory_log_path
  → TradingAgentsGraph(config=cfg).propagate(ticker, trade_date)
  → propagate() writes message_tool.log + reports/ as it runs
  → on success: status='succeeded', final_rating=parse_rating(final),
    completed_at=now
  → calls memory_mirror.sync(user_id) to refresh Postgres mirror
  → on exception: status='failed', error_summary=str(e)[:500],
    error_detail=traceback (owner-only access)

─ Live monitor (parallel to worker) ──────────────────────────────────
Frontend (Live page)
  → polls every 2s: GET /api/runs/{id}/tail?since=<byte_offset>
FastAPI runs.tail()
  → loads Run, checks user_id matches → 404 if not
  → opens results_path/message_tool.log at offset `since`
  → reads up to MAX_TAIL_BYTES (64KB), returns
    { content, next_offset, status }
  → if status terminal, frontend stops polling
  → if file missing yet (queued), returns
    { content:"", next_offset:0, status:"queued" }
```

### 5.3 Browse / portfolio

```
History list
  → GET /api/runs?ticker=&from=&to=&rating=&status=succeeded&limit=50
  → returns Run rows filtered by user_id (always)

Single run detail
  → GET /api/runs/{id}
  → returns { run, report_sections: { market, sentiment, news,
              fundamentals, investment_plan, trader_plan, final } }
  → each section is markdown read from disk via user_root helper
  → frontend renders with react-markdown + syntax highlight

Portfolio summary
  → GET /api/portfolio/summary
  → portfolio_calc.summary(user_id):
      entries = SELECT * FROM memory_entry
                WHERE user_id=? AND status='resolved'
                ORDER BY trade_date
      sizes   = rating → {Buy:1, Over:0.5, Hold:0, Under:-0.5, Sell:-1}
      pnl[i]  = size[i] * realized_return[i]
      cumulative = prefix-sum
      return { curve, win_rate, sharpe, max_dd, trade_count }
  → refreshed when memory_mirror.sync runs (per-run trigger)

Per-ticker
  → GET /api/portfolio/ticker/{ticker}
  → fetch yfinance prices for [first_date - 30d, latest_date + 30d]
    (cached on disk for 24h via existing tradingagents/dataflows helper)
  → join with memory entries for that ticker
  → return { prices: [(date, close)], decisions: [(date, rating, return)] }
```

**Flow-level caveats:**

1. **Sharpe is computed from per-decision realized returns** (each decision is an observation), not from daily mark-to-market. This is a simplification; the design doc surfaces the limitation. A daily MTM version is a v2 concern.
2. **yfinance call in the request path** for per-ticker view is slow on cold cache: 1–3 second first hit per ticker. Cached to disk for 24h.
3. **No sub-2s streaming** during a run. If the worker stalls on an LLM call for 30s, the user sees no update for 30s. Acceptable for v1, explicit non-goal.

## 6. Error Handling

**Auth**
- Invalid/expired JWT → FastAPI 401 `{error:"unauthenticated"}`; Next.js interceptor pushes to `/auth/signin` preserving `callbackUrl`.
- GitHub OAuth callback failure → NextAuth error page with retry.
- `NEXTAUTH_SECRET` drift after redeploy → log a single warning per request burst, treat as 401, don't crash.

**Run lifecycle**
- Worker crash mid-run → arq retries once on `WorkerError` only; no retry on `TradingAgentsGraph` exceptions (LLM/API failures cost money). On final failure, `Run` row records `error_summary` (str-truncated) and `error_detail` (full traceback, owner-only).
- Worker process killed (OOM, container restart) → `orphan_sweeper` cron sweeps `running` runs with no heartbeat >10 min to `failed` with `error_summary='worker_lost'`.
- Duplicate launch (same user, ticker, date) → 409 with link to existing run. Re-launch via `?force=true` archives the old `results_path` to `<path>.old-<timestamp>/`.

**Live monitor tail**
- File doesn't exist yet (queued) → return empty content + `status:"queued"`. Frontend keeps polling.
- File shrinks between polls → if `since > current_size`, reset `next_offset=0` and resend from start.
- Path-escape attempts in `run_id` → `run_id` typed as UUID at the route signature; non-UUID returns 422 before `user_root` is called.

**Filesystem**
- Disk full → worker catches `OSError`, marks Run failed, emits metric. Per-section writes are atomic; no half-written reports.
- `user_root` rejects any `user_id` that doesn't match the UUID regex.

**External APIs**
- LLM provider 429/5xx → handled inside `tradingagents/llm_clients` (existing retry layer).
- yfinance fetch fails → 502 `{error:"price_data_unavailable", ticker}`; UI shows decision list without price overlay.
- GitHub OAuth outage → can't sign in; surfaced via NextAuth error page. No fallback in v1.

**Memory mirror**
- Parse error on malformed entry → log + skip that entry, continue with rest. Disk remains canonical; next sync recovers after fix.
- Race between simultaneous syncs → Postgres advisory lock keyed on `('memory_mirror', user_id)`; second sync no-ops with a warning.

## 7. Testing

**Unit (cheap, lots)**
- `user_root` adversarial inputs: `..`, absolute paths, NUL bytes, unicode normalization tricks, empty string. Parametrized.
- `portfolio_calc`: rating→size mapping, cumulative sum, Sharpe (synthetic resolved entries fixture), max drawdown edge cases (single trade, all-positive, all-negative).
- `memory_mirror`: parse fixture markdown files (good, malformed, mixed pending/resolved); assert Postgres state.
- JWT verification: valid, expired, bad signature, missing claims, wrong algorithm.

**Integration (medium count)**
- Launch run flow: POST /runs → assert arq enqueue + Run row created → fake worker marks succeeded → GET /runs/{id} returns expected payload.
- Live monitor tail: write to a temp `message_tool.log` over time, poll endpoint with successive offsets, assert byte-correct chunks. Cover "file doesn't exist yet" and "file shrunk" edges.
- Portfolio summary end-to-end: seed Postgres with N resolved entries → GET /portfolio/summary → assert curve points, win rate, Sharpe within tolerance.
- Per-user isolation: two users each launch a run; assert each user's `GET /runs` returns only their own. `GET /runs/{other_users_id}` must 404 (not 403 — avoid existence oracle).

**E2E smoke (Playwright, 1–2 tests)**
- Sign in with mocked OAuth provider → launch a run with a stub `TradingAgentsGraph` writing fixture markdown → watch live monitor produce content → view final report → see entry on portfolio page.

**Not tested in this layer:**
- Real LLM API calls (covered by existing `tradingagents` test suite).
- yfinance live data (mocked at the boundary).
- GitHub OAuth itself (trust upstream; cover *our* JWT verification only).

## 8. Out of Scope (v2 candidates)

- Per-user LLM API keys (v1 uses worker-env-var keys shared across users).
- Google SSO (GitHub-only in v1).
- Hybrid private/shared workspace (purely per-user in v1).
- User-configurable rating→size mapping (constant in v1).
- Daily mark-to-market Sharpe (per-decision in v1).
- Websocket/SSE streaming for live monitor (HTTP polling only in v1).
- Multi-region / horizontal scaling (single-instance worker pool in v1).

## 9. Implementation Order (suggestion, not locked)

The design is one app, but implementation lands in waves to keep slices shippable:

1. **Wave 1 — Skeleton + History (read-only)**: Auth, `user_root`, run-list, run-detail markdown rendering. No worker, no portfolio. Reads from disk only.
2. **Wave 2 — Launch + Live monitor**: arq worker, POST /runs, file-tail endpoint, LiveLogStream component. Existing runs from Wave 1 still browsable.
3. **Wave 3 — Portfolio**: memory_mirror, portfolio_calc, P&L curve, per-ticker chart with yfinance integration.

Each wave is independently deployable and provides standalone value.

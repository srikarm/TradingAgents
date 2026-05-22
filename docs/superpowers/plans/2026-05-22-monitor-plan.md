# Wave 5.2 Monitor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the daily Monitor — at each user's chosen briefing time, automatically dispatch a full TradingAgents analysis for every ticker on that user's watchlist. Runs land in `/history` tagged `triggered_by='monitor'`.

**Architecture:** One arq cron tick every 15 minutes runs `find_due_users()` and per-due-user dispatches all watchlist tickers via the existing `dispatch_run()`. New `users` columns (`monitor_enabled`, `briefing_time_local`, `briefing_tz`) drive the schedule; new `runs.triggered_by` column distinguishes monitor runs from manual ones. Inline `MonitorSection` on `/watchlist` is the only new surface; settings persist via `PATCH /me/monitor`.

**Tech Stack:** SQLAlchemy 2 async + Alembic, FastAPI, arq cron, Pydantic v2, Next.js 15 App Router, Playwright, pytest.

---

## Verified before writing this plan

- **Alembic head**: `d3e4f5a6b7c8` (watchlists migration). New migration's `down_revision = "d3e4f5a6b7c8"`.
- **arq WorkerSettings** lives at `server/app/workers/worker.py`. Already imports `from arq.cron import cron`. Already has one `cron_jobs` entry (`orphan_sweeper`, every 5 min). The monitor cron joins as a second entry.
- **Existing cron pattern** (in `server/app/workers/tasks.py:orphan_sweeper`): takes `ctx: dict`, opens its own session via `_session_factory_for_worker()`, does work, commits, logs. `monitor_tick` follows the same shape.
- **GET /me** at `server/app/routers/me.py` returns `UserOut` from `server/app/schemas/user.py:UserOut`. UserOut has `id, github_id, email, created_at`. We extend it with 3 monitor fields; `google_sub` stays internal (not exposed).
- **`web/lib/api.ts`** has `patch<T>` already (shipped in Wave 5.1 Task 4). We add `updateMonitor` next to existing watchlist methods.
- **RunCard** at `web/components/RunCard.tsx` renders ticker + trade_date + status + rating. The `Monitor` badge slots inline next to ticker.
- **dispatch_run** at `server/app/services/run_dispatcher.py:36` — current signature accepts `body: RunCreate`. We add a kwarg `triggered_by: str = "manual"`.

---

## ⚠️ Worktree discipline — mandatory pre-commit verification

The Wave 4 item 2 + 3 implementers each landed in a worktree initialized at a stale upstream commit. Item 2 accidentally committed to LOCAL main; item 3 caught the mismatch and `reset --hard`'d before working. Same discipline applies.

**Before EVERY commit, run all three checks:**

```bash
pwd                                                              # MUST start with `.claude/worktrees/agent-`
git rev-parse --abbrev-ref HEAD                                  # MUST start with `worktree-agent-` or `feature/monitor`
git -C /Users/erikgunawansupriatna/TradingAgents rev-parse main  # MUST equal the plan-commit SHA the dispatcher passed in your spawn message — unchanged
```

The dispatcher (the parent session that spawns you) will quote the **plan-commit SHA** in your spawn message — that's the SHA `main` was at the instant you were dispatched. Treat it as the only authoritative value; do NOT hardcode SHAs from this file (they're hints and may drift after amends).

If ANY check fails, STOP and report BLOCKED. If your worktree's HEAD is at an unrelated upstream SHA (e.g., `61522e1`), the first remediation is `git fetch --all && git reset --hard <dispatcher-provided-SHA>` BEFORE writing any code.

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

Expected: `Already up to date.` or fast-forward to fork/main HEAD (which includes this plan doc).

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b feature/monitor
git push -u fork feature/monitor
```

Expected: `Switched to a new branch 'feature/monitor'`; `* [new branch] feature/monitor -> feature/monitor`.

---

## Phase 2 — Server: migration + model + schemas + service + cron + endpoint + tests

### Task 2: Write failing pytest tests

**Files:**
- Create: `server/tests/test_monitor.py`
- Create: `server/tests/test_me_monitor_endpoint.py`

- [ ] **Step 1: Create `test_monitor.py`** with 16 tests covering `find_due_users`, `dispatch_user_watchlist`, `monitor_tick`, and the `Run.triggered_by` column:

```python
# server/tests/test_monitor.py
"""Tests for the Wave 5.2 Monitor — daily cron + due-users + dispatch loop."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.user import User
from app.models.run import Run, RunStatus
from app.models.watchlist import WatchlistItem
from app.services.monitor import (
    find_due_users,
    dispatch_user_watchlist,
)


def _make_user(github_id: str, *, enabled: bool, time_local: str | None, tz: str | None) -> User:
    return User(
        id=uuid.uuid4(),
        github_id=github_id,
        monitor_enabled=enabled,
        briefing_time_local=time_local,
        briefing_tz=tz,
    )


@pytest.mark.asyncio
async def test_find_due_users_jakarta_at_briefing(db_session):
    """User at 07:00 Asia/Jakarta, tick at 00:00 UTC (= 07:00 WIB) → due."""
    u = _make_user("u-jakarta", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert [x.id for x in due] == [u.id]


@pytest.mark.asyncio
async def test_find_due_users_within_window(db_session):
    """Tick at 00:14 UTC (still in 15-min window after 07:00 WIB briefing) → due."""
    u = _make_user("u-jakarta-2", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 14, 59, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_just_past_window(db_session):
    """Tick at 00:15 UTC → window has passed, NOT due."""
    u = _make_user("u-jakarta-3", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 15, 1, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_before_briefing(db_session):
    """Tick at 23:45 UTC (= 06:45 WIB next day) — window ends 1 min before briefing → NOT due."""
    u = _make_user("u-jakarta-4", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 23, 45, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_disabled_user(db_session):
    """monitor_enabled=False → NOT due regardless of time match."""
    u = _make_user("u-off", enabled=False, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_null_tz(db_session):
    """briefing_tz=None → NOT due (incomplete config)."""
    u = _make_user("u-no-tz", enabled=True, time_local="07:00", tz=None)
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_null_time(db_session):
    """briefing_time_local=None → NOT due."""
    u = _make_user("u-no-time", enabled=True, time_local=None, tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)
    assert u.id not in [x.id for x in due]


@pytest.mark.asyncio
async def test_find_due_users_dst_spring_forward(db_session):
    """US/Eastern DST spring-forward 2026-03-08: 02:00-03:00 EST is skipped.
    A 02:30 briefing on that day resolves via zoneinfo to the post-transition
    equivalent without crashing."""
    u = _make_user("u-dst", enabled=True, time_local="02:30", tz="US/Eastern")
    db_session.add(u)
    await db_session.commit()
    # 06:30 UTC on 2026-03-08 is 02:30 EST — but DST skipped 02:00-03:00, so
    # that local time becomes 03:30 EDT. The function should not raise.
    now_utc = datetime(2026, 3, 8, 6, 30, 0, tzinfo=timezone.utc)
    due = await find_due_users(db_session, now_utc)  # should not raise
    # We accept either due=True (zoneinfo resolves to post-transition) or due=False;
    # the contract is: no exception.
    assert isinstance(due, list)


@pytest.mark.asyncio
async def test_find_due_users_two_users_only_one_due(db_session):
    """Two users in different TZs, only one in window."""
    a = _make_user("u-a", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    b = _make_user("u-b", enabled=True, time_local="07:00", tz="America/New_York")
    db_session.add_all([a, b])
    await db_session.commit()
    now_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)  # 07:00 WIB; 20:00 prev day NYC
    due_ids = [x.id for x in await find_due_users(db_session, now_utc)]
    assert a.id in due_ids
    assert b.id not in due_ids


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_three_tickers(db_session, monkeypatch):
    """3 watchlist tickers, no prior runs → 3 Run rows, all triggered_by='monitor', QUEUED."""
    u = _make_user("u-disp", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    for t in ["AAPL", "MSFT", "GOOG"]:
        db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker=t))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result == {"dispatched": 3, "skipped_dup": 0, "failed": 0}

    runs = (await db_session.execute(
        select(Run).where(Run.user_id == u.id)
    )).scalars().all()
    assert len(runs) == 3
    assert all(r.triggered_by == "monitor" for r in runs)
    assert all(r.status == RunStatus.QUEUED for r in runs)
    assert mock_pool.enqueue_job.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_skips_existing(db_session, monkeypatch):
    """Manual run already exists for ticker — DuplicateRunningError caught silently."""
    u = _make_user("u-dup", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="AAPL"))
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="MSFT"))
    # Existing QUEUED run for AAPL today (trade_date "2026-05-22" in Asia/Jakarta).
    db_session.add(Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date="2026-05-22",
        status=RunStatus.QUEUED, results_path="/tmp/x",
        triggered_by="manual",
    ))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result == {"dispatched": 1, "skipped_dup": 1, "failed": 0}


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_empty(db_session, monkeypatch):
    """User with empty watchlist → no errors, no rows."""
    u = _make_user("u-empty", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    await db_session.commit()

    mock_pool = AsyncMock()
    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result == {"dispatched": 0, "skipped_dup": 0, "failed": 0}


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_enqueue_fails(db_session, monkeypatch):
    """arq enqueue raises → run row marked FAILED, loop continues."""
    u = _make_user("u-fail", enabled=True, time_local="07:00", tz="Asia/Jakarta")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="BAD"))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

    result = await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc)
    )
    assert result["failed"] == 1
    failed = (await db_session.execute(
        select(Run).where(Run.user_id == u.id)
    )).scalar_one()
    assert failed.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_triggered_by_default_is_manual(db_session):
    """Existing Run rows (created via the runs router) get triggered_by='manual'."""
    u = _make_user("u-tr", enabled=False, time_local=None, tz=None)
    db_session.add(u)
    await db_session.commit()
    run = Run(
        id=uuid.uuid4(), user_id=u.id, ticker="AAPL", trade_date="2026-05-22",
        status=RunStatus.QUEUED, results_path="/tmp/x",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.triggered_by == "manual"


@pytest.mark.asyncio
async def test_dispatch_user_watchlist_trade_date_in_user_tz(db_session, monkeypatch):
    """trade_date reflects USER's TZ date, not UTC date."""
    # 22:00 UTC on 2026-05-22 == 05:00 WIB on 2026-05-23. User in Jakarta should
    # get trade_date="2026-05-23".
    u = _make_user("u-tz-date", enabled=True, time_local="05:00", tz="Asia/Jakarta")
    db_session.add(u)
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=u.id, ticker="AAPL"))
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    await dispatch_user_watchlist(
        db_session, mock_pool, u, datetime(2026, 5, 22, 22, 0, 0, tzinfo=timezone.utc)
    )
    run = (await db_session.execute(select(Run).where(Run.user_id == u.id))).scalar_one()
    assert run.trade_date == "2026-05-23"


@pytest.mark.asyncio
async def test_dispatch_persists_across_sessions(async_client_authed, authed_user, db_session):
    """Monitor-dispatched run survives session close (guards against missing-commit regressions)."""
    # This test mirrors the pattern from Wave 5.1 — open a fresh session after the dispatch
    # and confirm the row exists. It's the same anti-pattern guard as test_add_persists_across_sessions
    # in test_watchlist.py.
    # (Implementation detail: use async_sessionmaker(db_session.bind) to open a fresh session.)
    from sqlalchemy.ext.asyncio import async_sessionmaker
    db_session.add(WatchlistItem(id=uuid.uuid4(), user_id=authed_user.id, ticker="PERSIST"))
    authed_user.monitor_enabled = True
    authed_user.briefing_time_local = "07:00"
    authed_user.briefing_tz = "Asia/Jakarta"
    await db_session.commit()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    await dispatch_user_watchlist(
        db_session, mock_pool, authed_user,
        datetime(2026, 5, 22, 0, 0, 0, tzinfo=timezone.utc),
    )

    fresh_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with fresh_factory() as fresh:
        row = (await fresh.execute(
            select(Run).where(Run.user_id == authed_user.id, Run.ticker == "PERSIST")
        )).scalar_one_or_none()
        assert row is not None, "dispatch should persist across sessions"
        assert row.triggered_by == "monitor"
```

- [ ] **Step 2: Create `test_me_monitor_endpoint.py`** with 7 endpoint tests:

```python
# server/tests/test_me_monitor_endpoint.py
"""Tests for PATCH /me/monitor + extended GET /me."""
import pytest


@pytest.mark.asyncio
async def test_get_me_includes_monitor_fields(async_client_authed):
    """GET /me returns the 3 new monitor fields (all null/false for new users)."""
    res = await async_client_authed.get("/me")
    assert res.status_code == 200
    body = res.json()
    assert body["monitor_enabled"] is False
    assert body["briefing_time_local"] is None
    assert body["briefing_tz"] is None


@pytest.mark.asyncio
async def test_patch_monitor_enable_valid(async_client_authed):
    """PATCH /me/monitor with valid enable payload → 200 + persisted + next_briefing_at."""
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True,
        "briefing_time_local": "07:00",
        "briefing_tz": "Asia/Jakarta",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["briefing_time_local"] == "07:00"
    assert body["briefing_tz"] == "Asia/Jakarta"
    assert "next_briefing_at" in body


@pytest.mark.asyncio
async def test_patch_monitor_enable_missing_time_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_tz": "Asia/Jakarta",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_enable_missing_tz_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "07:00",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_invalid_tz_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "07:00", "briefing_tz": "Not/A/Zone",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_invalid_time_returns_422(async_client_authed):
    res = await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "25:00", "briefing_tz": "Asia/Jakarta",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_monitor_disable_preserves_config(async_client_authed):
    """Disable preserves time+tz so re-enable restores prior config."""
    await async_client_authed.patch("/me/monitor", json={
        "enabled": True, "briefing_time_local": "07:00", "briefing_tz": "Asia/Jakarta",
    })
    res = await async_client_authed.patch("/me/monitor", json={"enabled": False})
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    # Time + tz should still be there (preserved for re-enable):
    assert body["briefing_time_local"] == "07:00"
    assert body["briefing_tz"] == "Asia/Jakarta"
```

Use the same inline-fixture pattern as `test_watchlist.py` (the Wave 5.1 precedent) for `async_client_authed` + `authed_user` in `test_me_monitor_endpoint.py`.

- [ ] **Step 3: Run to verify all tests fail**

```bash
cd server && uv run pytest tests/test_monitor.py tests/test_me_monitor_endpoint.py -v 2>&1 | tail -20
```

Expected: 23 failures (16 + 7). Likely `ImportError: cannot import name 'find_due_users' from 'app.services.monitor'` and/or `AttributeError` on `User.monitor_enabled` (column doesn't exist yet).

No commit yet — combined with Task 3.

---

### Task 3: Implement migration + model + schemas + service + cron + endpoint

**Files:**
- Create: `server/alembic/versions/e4f5a6b7c8d9_add_monitor_columns.py` (slug is suggestive; revision ID can be any 12-char hex)
- Modify: `server/app/models/user.py`
- Modify: `server/app/models/run.py`
- Modify: `server/app/schemas/user.py` (extend `UserOut`)
- Create: `server/app/schemas/monitor.py`
- Create: `server/app/services/monitor.py`
- Modify: `server/app/services/run_dispatcher.py` (add `triggered_by` kwarg)
- Modify: `server/app/routers/me.py` (add `PATCH /me/monitor`)
- Modify: `server/app/workers/worker.py` (register cron entry)
- Modify: `server/alembic/env.py` (no change needed — models already imported)
- Modify: `server/tests/conftest.py` (no change needed — same as Wave 5.1 pattern)

- [ ] **Step 1: Write the migration**

Create `server/alembic/versions/e4f5a6b7c8d9_add_monitor_columns.py`:

```python
"""add_monitor_columns

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-22
"""
import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("monitor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("briefing_time_local", sa.String(5), nullable=True))
    op.add_column("users", sa.Column("briefing_tz", sa.String(64), nullable=True))
    op.add_column("runs", sa.Column("triggered_by", sa.String(16), nullable=False, server_default="manual"))


def downgrade() -> None:
    op.drop_column("runs", "triggered_by")
    op.drop_column("users", "briefing_tz")
    op.drop_column("users", "briefing_time_local")
    op.drop_column("users", "monitor_enabled")
```

- [ ] **Step 2: Add columns to `User` model**

Edit `server/app/models/user.py`. Add inside the `User` class, after the existing columns:

```python
from sqlalchemy import Boolean, DateTime, String, func, select, false
# (false is new — add to existing sqlalchemy import line)
# ...

class User(Base):
    __tablename__ = "users"
    # ... existing columns ...
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    briefing_time_local: Mapped[str | None] = mapped_column(String(5), nullable=True)
    briefing_tz: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

- [ ] **Step 3: Add `triggered_by` to `Run` model**

Edit `server/app/models/run.py`. Add after the `error_summary` / `error_detail` columns:

```python
    triggered_by: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="manual"
    )
```

- [ ] **Step 4: Extend `UserOut` schema**

Edit `server/app/schemas/user.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    id: uuid.UUID
    github_id: str | None
    email: str | None
    created_at: datetime
    monitor_enabled: bool
    briefing_time_local: str | None
    briefing_tz: str | None

    model_config = ConfigDict(from_attributes=True)
```

(Note: `github_id` is changed from `str` to `str | None` to match the current `User.github_id: Mapped[str | None]` shape — this is a bugfix that snuck in here. The existing route works because Pydantic v2 coerces None to None for `str` typing but emits no error; making it explicit prevents future schema-validation surprises.)

- [ ] **Step 5: Create `MonitorOut` + `MonitorUpdate` schemas**

Create `server/app/schemas/monitor.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator


_VALID_TZ = available_timezones()


class MonitorUpdate(BaseModel):
    enabled: bool
    briefing_time_local: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    briefing_tz: str | None = None

    @field_validator("briefing_tz")
    @classmethod
    def _validate_tz(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_TZ:
            raise ValueError(f"unknown timezone: {v}")
        return v


class MonitorOut(BaseModel):
    enabled: bool
    briefing_time_local: str | None
    briefing_tz: str | None
    next_briefing_at: datetime | None

    model_config = ConfigDict(from_attributes=False)
```

- [ ] **Step 6: Create the Monitor service**

Create `server/app/services/monitor.py`:

```python
"""Wave 5.2 Monitor — daily cron + due-users + per-user dispatch."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.run import Run
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.run import RunCreate
from app.services.run_dispatcher import DuplicateRunningError, dispatch_run

logger = logging.getLogger(__name__)


WINDOW = timedelta(minutes=15)


async def find_due_users(
    db: AsyncSession,
    now_utc: datetime,
    window: timedelta = WINDOW,
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
            continue
        local_now = now_utc.astimezone(tz)
        local_window_start = (now_utc - window).astimezone(tz)
        try:
            hh, mm = map(int, u.briefing_time_local.split(":"))
            briefing_today = local_now.replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
        except (ValueError, AttributeError):
            continue
        if local_window_start < briefing_today <= local_now:
            due.append(u)
    return due


async def dispatch_user_watchlist(
    db: AsyncSession,
    pool,
    user: User,
    now_utc: datetime,
) -> dict:
    """Dispatch every watchlist ticker for this user as a Run with triggered_by='monitor'."""
    items = (await db.execute(
        select(WatchlistItem.ticker).where(WatchlistItem.user_id == user.id)
    )).scalars().all()

    settings = get_settings()
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
            logger.exception("monitor: dispatch failed for user=%s ticker=%s", user.id, ticker)
            failed += 1
    return {"dispatched": dispatched, "skipped_dup": skipped_dup, "failed": failed}


def compute_next_briefing_at(user: User, now_utc: datetime) -> datetime | None:
    """Returns the next UTC instant the user's briefing will fire, or None if disabled."""
    if not user.monitor_enabled or not user.briefing_time_local or not user.briefing_tz:
        return None
    try:
        tz = ZoneInfo(user.briefing_tz)
    except Exception:
        return None
    local_now = now_utc.astimezone(tz)
    hh, mm = map(int, user.briefing_time_local.split(":"))
    briefing_today = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if briefing_today > local_now:
        return briefing_today.astimezone(timezone.utc)
    return (briefing_today + timedelta(days=1)).astimezone(timezone.utc)


# Cron entry (called by arq worker). Has to open its own session because
# cron contexts don't have a request-scoped db dep.
async def monitor_tick(ctx: dict) -> dict:
    """Fires every 15 min. Dispatches due users' watchlists."""
    from app.db import get_session_factory  # avoid import cycle at module load
    from app.services.redis_pool import get_pool  # arq pool used inside the cron
    factory = get_session_factory()
    pool = await get_pool()
    now_utc = datetime.now(timezone.utc)
    results = []
    async with factory() as session:
        due = await find_due_users(session, now_utc)
        for user in due:
            r = await dispatch_user_watchlist(session, pool, user, now_utc)
            results.append({"user_id": str(user.id), **r})
    if results:
        logger.info("monitor_tick: dispatched %d user(s): %s", len(results), results)
    return {"users_dispatched": len(results), "details": results}
```

> **Implementer note**: `get_pool()` in `services/redis_pool.py` — confirm it returns an arq pool usable here. If it requires an existing FastAPI app context, factor out a worker-friendly variant (`create_worker_pool()`) that just opens a fresh arq connection.

- [ ] **Step 7: Add `triggered_by` kwarg to `dispatch_run`**

Edit `server/app/services/run_dispatcher.py`. Update the function signature and the `Run(...)` constructor:

```python
async def dispatch_run(
    *,
    session: AsyncSession,
    pool: _PoolProto,
    user_id: uuid.UUID,
    dashboard_dir: Path,
    body: RunCreate,
    triggered_by: str = "manual",   # NEW
) -> Run:
    # ... existing duplicate check unchanged ...
    target = user_run_dir(dashboard_dir, str(user_id), ticker, trade_date)
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=trade_date,
        status=RunStatus.QUEUED,
        results_path=str(target),
        created_at=datetime.now(timezone.utc),
        triggered_by=triggered_by,   # NEW
    )
    # ... rest unchanged ...
```

The existing call site in `routers/runs.py:create_run` doesn't need any change — it inherits the default `"manual"`.

- [ ] **Step 8: Add `PATCH /me/monitor` endpoint + extend `GET /me`**

Edit `server/app/routers/me.py`:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.monitor import MonitorOut, MonitorUpdate
from app.schemas.user import UserOut
from app.services.monitor import compute_next_briefing_at

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me/monitor", response_model=MonitorOut)
async def update_monitor(
    body: MonitorUpdate = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorOut:
    if body.enabled and (body.briefing_time_local is None or body.briefing_tz is None):
        raise HTTPException(
            status_code=422,
            detail={"error": "briefing_time_local and briefing_tz are required when enabling"},
        )
    user.monitor_enabled = body.enabled
    if body.briefing_time_local is not None:
        user.briefing_time_local = body.briefing_time_local
    if body.briefing_tz is not None:
        user.briefing_tz = body.briefing_tz
    await db.commit()
    await db.refresh(user)
    return MonitorOut(
        enabled=user.monitor_enabled,
        briefing_time_local=user.briefing_time_local,
        briefing_tz=user.briefing_tz,
        next_briefing_at=compute_next_briefing_at(user, datetime.now(timezone.utc)),
    )
```

- [ ] **Step 9: Register the cron in `WorkerSettings`**

Edit `server/app/workers/worker.py`. Add the import + new cron entry:

```python
from arq.cron import cron
from app.workers.tasks import orphan_sweeper, run_propagate
from app.services.monitor import monitor_tick   # NEW

# Register every ORM model with Base.metadata BEFORE the worker issues any flush.
from app.models import memory_entry as _memory_entry  # noqa: F401
from app.models import run as _run  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.models import watchlist as _watchlist  # noqa: F401   # NEW (in case it isn't already)

from app.services.redis_pool import get_redis_settings


class WorkerSettings:
    functions = [run_propagate]
    cron_jobs = [
        cron(orphan_sweeper, minute=set(range(0, 60, 5))),
        cron(monitor_tick, minute={0, 15, 30, 45}),   # NEW — every 15 minutes
    ]
    redis_settings = get_redis_settings()
    max_jobs = 1
    job_timeout = 60 * 60
```

If `watchlist` isn't already imported in the noqa block, add it (the monitor service queries the `watchlist_items` table; the worker must know about the model).

- [ ] **Step 10: Run migration + tests**

```bash
cd server
uv run alembic upgrade head
uv run pytest tests/test_monitor.py tests/test_me_monitor_endpoint.py -v 2>&1 | tail -30
uv run pytest -q 2>&1 | tail -5
```

Expected: migration head is `e4f5a6b7c8d9`; all 23 new tests pass (16 + 7); full suite passes with zero regressions (190 prior + 23 new = 213 tests).

- [ ] **Step 11: Verify migration round-trip**

```bash
cd server
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: both succeed; final head is `e4f5a6b7c8d9`.

- [ ] **Step 12: Worktree discipline + commit**

Run the three pre-commit checks (worktree path / branch / parent main SHA). All must pass.

```bash
git add server/alembic/versions/e4f5a6b7c8d9_add_monitor_columns.py \
        server/app/models/user.py \
        server/app/models/run.py \
        server/app/schemas/user.py \
        server/app/schemas/monitor.py \
        server/app/services/monitor.py \
        server/app/services/run_dispatcher.py \
        server/app/routers/me.py \
        server/app/workers/worker.py \
        server/tests/test_monitor.py \
        server/tests/test_me_monitor_endpoint.py

git commit -m "$(cat <<'EOF'
feat(server): monitor cron + dispatch + PATCH /me/monitor (Wave 5.2)

Migration e4f5a6b7c8d9 adds three columns to users (monitor_enabled
default false, briefing_time_local, briefing_tz) and one column to
runs (triggered_by default 'manual' — backfills existing rows).

services/monitor.py:
- find_due_users(now_utc, window=15min): selects users whose briefing
  instant in their IANA tz fell in (now-window, now]
- dispatch_user_watchlist(user, now_utc): iterates the user's
  watchlist_items, calls dispatch_run() with triggered_by='monitor'.
  Catches DuplicateRunningError silently for tickers already running
  today; counts dispatched/skipped_dup/failed.
- compute_next_briefing_at(user, now_utc): used by PATCH /me/monitor
  response; returns next UTC firing instant.
- monitor_tick(ctx): arq cron entry; opens its own session, finds
  due users, dispatches each user's watchlist. Registered in
  WorkerSettings.cron_jobs at minute={0,15,30,45}.

dispatch_run now accepts triggered_by kwarg (default 'manual'). The
existing routers/runs.py call site is unchanged — it inherits the
default.

PATCH /me/monitor enables/disables monitoring and persists time+tz.
Pydantic validates HH:MM format + IANA tz against
zoneinfo.available_timezones(). Disabling preserves time+tz so
re-enable restores prior config. GET /me extended with the 3 new
fields plus user.github_id typed as Optional.

23 new pytest tests: 16 monitor service tests (window math, DST
spring-forward safety, two-user-TZ isolation, dispatch with
duplicate skip, empty watchlist no-op, arq-fail-marks-FAILED,
cross-session persistence) + 7 endpoint tests (valid enable,
missing fields, invalid tz, invalid time, disable preserves config).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

git push fork HEAD:feature/monitor
```

---

## Phase 3 — Web: API client + MonitorSection + history badge

### Task 4: Extend api.ts with monitor methods + types

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/lib/types.ts`
- Modify: `web/lib/openapi-types.ts` (regenerated)

- [ ] **Step 1: Regenerate OpenAPI types**

```bash
cd web && npm run codegen
```

Expected: `web/lib/openapi-types.ts` updates to include `MonitorOut`, `MonitorUpdate`, and the new `/me/monitor` PATCH operation. UserOut gains 3 new fields.

- [ ] **Step 2: Add branded type exports to `web/lib/types.ts`**

```typescript
export type MonitorOut = components["schemas"]["MonitorOut"];
export type MonitorUpdate = components["schemas"]["MonitorUpdate"];
```

(Note: `UserOut` already exported; the new fields ride along automatically.)

- [ ] **Step 3: Add api methods**

In `web/lib/api.ts`, add `MonitorOut`/`MonitorUpdate` to the type imports at the top, then add this method to the `api` object (place between `removeFromWatchlist` and `portfolioSummary` to keep monitor next to watchlist):

```typescript
updateMonitor: (body: MonitorUpdate) =>
  patch<MonitorOut>("/me/monitor", body),
```

- [ ] **Step 4: Verify build**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Step 5: Worktree discipline + commit**

```bash
git add web/lib/api.ts web/lib/types.ts web/lib/openapi-types.ts
git commit -m "feat(web): add updateMonitor api method + Monitor types

Mirrors the patch<T> helper pattern from Wave 5.1. Regenerates
openapi-types to surface MonitorOut/MonitorUpdate + the extended
UserOut with the 3 new monitor fields.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push fork HEAD:feature/monitor
```

---

### Task 5: Create `MonitorSection` component + integrate into `/watchlist`

**Files:**
- Create: `web/app/watchlist/MonitorSection.tsx`
- Modify: `web/app/watchlist/page.tsx`

- [ ] **Step 1: Create the `MonitorSection` component**

Create `web/app/watchlist/MonitorSection.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { MonitorOut } from "@/lib/types";

type MonitorState = {
  enabled: boolean;
  briefingTimeLocal: string | null;
  briefingTz: string | null;
  nextBriefingAt: string | null;
};

function browserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC";
  } catch {
    return "UTC";
  }
}

function formatCountdown(targetIso: string | null): string {
  if (!targetIso) return "";
  const ms = new Date(targetIso).getTime() - Date.now();
  if (ms <= 0) return "due now";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

export default function MonitorSection({
  initial,
  tickerCount,
  tickers,
}: {
  initial: MonitorState;
  tickerCount: number;
  tickers: string[];
}) {
  const router = useRouter();
  const [state, setState] = useState<MonitorState>(initial);
  const [countdown, setCountdown] = useState(() => formatCountdown(initial.nextBriefingAt));
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const tick = () => setCountdown(formatCountdown(state.nextBriefingAt));
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, [state.nextBriefingAt]);

  async function apply(next: Partial<MonitorState>) {
    const merged = { ...state, ...next };
    setState(merged);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.updateMonitor({
          enabled: merged.enabled,
          briefing_time_local: merged.briefingTimeLocal,
          briefing_tz: merged.briefingTz,
        });
        setState({
          enabled: res.enabled,
          briefingTimeLocal: res.briefing_time_local,
          briefingTz: res.briefing_tz,
          nextBriefingAt: res.next_briefing_at,
        });
      } catch (e) {
        console.error("monitor save failed", e);
      }
    }, 800);
  }

  async function onEnable() {
    const tz = state.briefingTz ?? browserTz();
    const time = state.briefingTimeLocal ?? "07:00";
    // Immediate POST so the user is "on" right away — bypass the 800ms debounce.
    try {
      const res = await api.updateMonitor({
        enabled: true, briefing_time_local: time, briefing_tz: tz,
      });
      setState({
        enabled: true,
        briefingTimeLocal: res.briefing_time_local,
        briefingTz: res.briefing_tz,
        nextBriefingAt: res.next_briefing_at,
      });
    } catch (e) {
      console.error("monitor enable failed", e);
    }
  }

  async function onDisable() {
    try {
      const res = await api.updateMonitor({ enabled: false });
      setState((s) => ({
        ...s,
        enabled: false,
        briefingTimeLocal: res.briefing_time_local,
        briefingTz: res.briefing_tz,
        nextBriefingAt: null,
      }));
    } catch (e) {
      console.error("monitor disable failed", e);
    }
  }

  // STATE A — monitor off
  if (!state.enabled) {
    const subtitle = tickerCount > 0
      ? `Auto-analyze your ${tickerCount} ${tickerCount === 1 ? "ticker" : "tickers"} once a day.`
      : "Add tickers above, then enable to auto-analyze them daily.";
    return (
      <div className="rounded-xl border border-border/60 bg-surface/40 p-4 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Sparkles className="h-4 w-4 text-fg-subtle" aria-hidden />
            <span className="text-sm font-medium text-fg">Daily monitor</span>
          </div>
          <button
            type="button"
            onClick={onEnable}
            disabled={tickerCount === 0}
            className="inline-flex h-8 items-center rounded-lg border border-brand/60 bg-brand/10 px-3 text-xs font-medium text-brand transition-colors hover:bg-brand/15 disabled:opacity-50"
          >
            Enable
          </button>
        </div>
        <p className="mt-1.5 text-xs text-fg-muted">{subtitle}</p>
      </div>
    );
  }

  // STATE B — monitor on
  const tickerSummary = tickers.length
    ? `we analyze ${tickerCount} ticker${tickerCount === 1 ? "" : "s"}` +
      (tickerCount > 0 ? ` (${tickers.slice(0, 3).join(", ")}${tickerCount > 3 ? ", …" : ""})` : "")
    : "no tickers on the watchlist yet";
  return (
    <div className="rounded-xl border border-brand/40 bg-surface/40 p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Sparkles className="h-4 w-4 text-brand" aria-hidden />
          <span className="text-sm font-medium text-fg">Daily monitor</span>
        </div>
        <span className="font-mono text-[11px] text-fg-subtle">
          Next briefing: {countdown}
        </span>
      </div>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-col gap-1 text-xs text-fg-subtle">
          Time
          <input
            type="time"
            value={state.briefingTimeLocal ?? "07:00"}
            onChange={(e) => apply({ briefingTimeLocal: e.target.value })}
            aria-label="Briefing time"
            className="h-9 w-32 rounded-lg border border-border/60 bg-surface/40 px-2 font-mono text-sm text-fg focus:border-brand/60 focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-fg-subtle">
          Timezone
          <input
            type="text"
            list="iana-tz-list"
            value={state.briefingTz ?? browserTz()}
            onChange={(e) => apply({ briefingTz: e.target.value })}
            aria-label="Timezone"
            className="h-9 w-56 rounded-lg border border-border/60 bg-surface/40 px-2 font-mono text-sm text-fg focus:border-brand/60 focus:outline-none"
          />
        </label>
        <button
          type="button"
          onClick={onDisable}
          className="h-9 rounded-lg border border-border/60 bg-surface/40 px-3 text-xs text-fg-muted hover:text-fg sm:ml-auto"
        >
          Disable
        </button>
      </div>
      <p className="mt-2 text-xs text-fg-muted">
        At {state.briefingTimeLocal} {state.briefingTz} each day, {tickerSummary}.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Integrate into `/watchlist` page**

Edit `web/app/watchlist/page.tsx`. Add the import + render the section between `PageHeader` and the existing `QuickAddForm`. Also fetch the user's monitor state via the existing `GET /me` call (or a new `api.me()` call if one doesn't exist):

```tsx
import MonitorSection from "./MonitorSection";
// ... at the top, after other imports ...

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");

  const [items, me] = await Promise.all([
    api.listWatchlist(),
    api.me(),   // adds 3 monitor fields + computes next_briefing_at client-side from briefing fields
  ]);

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
          <MonitorSection
            initial={{
              enabled: me.monitor_enabled,
              briefingTimeLocal: me.briefing_time_local,
              briefingTz: me.briefing_tz,
              nextBriefingAt: null,  // page renders cold; component re-fetches via PATCH responses
            }}
            tickerCount={items.length}
            tickers={items.map((i) => i.ticker)}
          />
          <QuickAddForm />
          <WatchlistTable initialItems={items} />
        </div>
      </main>
    </>
  );
}
```

If `api.me()` doesn't exist, add it to `web/lib/api.ts` next to the existing methods:

```typescript
me: () => get<UserOut>("/me"),
```

(Add `UserOut` to the type imports at the top.)

- [ ] **Step 3: Verify build**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -10
```

Expected: build succeeds; `/watchlist` route entry shows a slight size bump (~2KB) from the new section.

- [ ] **Step 4: Worktree discipline + commit**

```bash
git add web/app/watchlist/MonitorSection.tsx web/app/watchlist/page.tsx web/lib/api.ts
git commit -m "feat(web): MonitorSection on /watchlist (Wave 5.2)

Inline section above QuickAddForm. Two visual states:
- OFF: single 'Enable' button (disabled if watchlist empty).
  Clicking Enable POSTs immediately with browser-detected TZ +
  '07:00' default.
- ON: time picker + tz input + 'Next briefing in Xh Ym' countdown
  (recomputes every 60s) + Disable button. Edits debounce-save at
  800ms idle.

GET /me fetched alongside listWatchlist via Promise.all (no extra
round-trip). Disable preserves time+tz server-side so re-enable
restores prior config.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push fork HEAD:feature/monitor
```

---

### Task 6: Add `Monitor` badge to `RunCard` (history list)

**Files:**
- Modify: `web/components/RunCard.tsx`

- [ ] **Step 1: Add the badge**

Edit `web/components/RunCard.tsx`. The badge slots inside the `<div className="flex items-baseline gap-2.5">` next to ticker/trade_date:

```tsx
import { ChevronRight, Sparkles } from "lucide-react";   // add Sparkles to existing import
// ...

<div className="flex items-baseline gap-2.5">
  <span className="font-mono text-[15px] font-semibold tracking-tight text-fg">
    {run.ticker}
  </span>
  <span className="font-mono text-[11px] text-fg-subtle tabular-nums">
    {run.trade_date}
  </span>
  {run.triggered_by === "monitor" && (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-brand"
      title="Auto-dispatched by the daily Monitor"
    >
      <Sparkles className="h-2.5 w-2.5" aria-hidden />
      Monitor
    </span>
  )}
</div>
```

The `run.triggered_by` field is already present on the `RunOut` Pydantic schema after Task 3, so the openapi-types regen in Task 4 picked it up automatically. If TypeScript complains that `triggered_by` is missing from the `Run` type, regenerate types:

```bash
cd web && npm run codegen
```

- [ ] **Step 2: Verify**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x AUTH_GOOGLE_ID=x AUTH_GOOGLE_SECRET=x npm run build 2>&1 | tail -5
```

Expected: build succeeds, no type errors.

- [ ] **Step 3: Worktree discipline + commit**

```bash
git add web/components/RunCard.tsx web/lib/openapi-types.ts
git commit -m "feat(web): Monitor badge in RunCard

Shows a small Sparkles+Monitor chip next to the ticker for runs
that were auto-dispatched by Wave 5.2's daily monitor. Reads
run.triggered_by directly from the regenerated openapi types.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push fork HEAD:feature/monitor
```

---

## Phase 4 — E2E

### Task 7: Playwright e2e for monitor flow

**Files:**
- Create: `web/tests/e2e/monitor.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
// web/tests/e2e/monitor.spec.ts
import { test, expect } from "@playwright/test";

async function signIn(page) {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/history/);
}

test.describe("/watchlist daily monitor", () => {
  test("enable monitor and see countdown", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");

    // Need at least one ticker on the watchlist for Enable to be active.
    await page.getByLabel("Ticker").fill("MON");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByRole("link", { name: "MON" })).toBeVisible();

    // Daily monitor card visible, currently OFF.
    await expect(page.getByText("Daily monitor")).toBeVisible();

    // Enable.
    await page.getByRole("button", { name: /^enable$/i }).click();
    await expect(page.getByText(/Next briefing:/i)).toBeVisible();
    await expect(page.getByLabel("Briefing time")).toBeVisible();
    await expect(page.getByLabel("Timezone")).toBeVisible();
  });

  test("disable preserves config; reload shows OFF state", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    // Pre-condition: monitor was enabled in the previous test (sequential e2e).
    await page.getByRole("button", { name: /^disable$/i }).click();
    await expect(page.getByText("Daily monitor")).toBeVisible();
    await expect(page.getByRole("button", { name: /^enable$/i })).toBeVisible();

    await page.reload();
    await expect(page.getByRole("button", { name: /^enable$/i })).toBeVisible();
  });

  test("change time updates the countdown copy", async ({ page }) => {
    await signIn(page);
    await page.goto("/watchlist");
    await page.getByRole("button", { name: /^enable$/i }).click();
    await page.getByLabel("Briefing time").fill("23:59");
    // Wait past the 800ms debounce.
    await page.waitForTimeout(1200);
    // The "at HH:MM" line should reflect the new time.
    await expect(page.getByText(/At 23:59/i)).toBeVisible();
  });

  test("Monitor badge appears on monitor-triggered run in /history", async ({ page, request }) => {
    // Seed a monitor-triggered run via direct API call (assuming the test fixture has an api key).
    // If the test environment doesn't support direct seeding, skip and rely on the manual smoke.
    test.skip(true, "Requires test-environment seed of a triggered_by='monitor' run; covered by manual smoke");
  });
});
```

- [ ] **Step 2: Run (deferred to CI)**

```bash
cd web && npx playwright test monitor.spec --reporter=line 2>&1 | tail -10
```

If the local dev server isn't running, tests will fail with `ECONNREFUSED`; that's expected — the pre-merge workflow dispatches against a fresh DB stack.

- [ ] **Step 3: Worktree discipline + commit**

```bash
git add web/tests/e2e/monitor.spec.ts
git commit -m "test(web): Playwright e2e for daily monitor

Four tests: enable from OFF → countdown visible; disable persists
across reload; change time updates the 'At HH:MM' label after the
800ms debounce; (skipped — Monitor badge in /history needs a
seeded triggered_by='monitor' run, deferred to manual smoke).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push fork HEAD:feature/monitor
```

---

## Phase 5 — Ship

### Task 8: PR + pre-merge dispatch + merge + smoke

**Files:** none (git + gh CLI).

- [ ] **Step 1: Open the PR**

```bash
gh pr create --repo erikgunawans/TradingAgents \
  --title "feat(monitor): daily Monitor cron — Wave 5.2" \
  --base main \
  --head feature/monitor \
  --body "$(cat <<'EOF'
## Summary

Wave 5.2 — the second sub-project of the agentic-monitoring effort. Adds a daily cron that, at each user's chosen briefing time, dispatches a full TradingAgents analysis for every ticker on the user's watchlist. Runs land in /history tagged \`triggered_by='monitor'\` with a small Sparkles badge.

## What's in this PR — 5 commits

1. \`feat(server): monitor cron + dispatch + PATCH /me/monitor (Wave 5.2)\` — migration e4f5a6b7c8d9, model/schema changes, services/monitor.py (find_due_users + dispatch_user_watchlist + monitor_tick), dispatch_run triggered_by kwarg, WorkerSettings cron entry at minute={0,15,30,45}, 23 pytest tests.
2. \`feat(web): add updateMonitor api method + Monitor types\` — patch<T> reuse from Wave 5.1.
3. \`feat(web): MonitorSection on /watchlist (Wave 5.2)\` — inline section with Enable/Disable, time picker, tz input, debounced auto-save, 60s countdown.
4. \`feat(web): Monitor badge in RunCard\` — Sparkles chip on /history rows where triggered_by='monitor'.
5. \`test(web): Playwright e2e for daily monitor\` — 3 active tests + 1 skipped (deferred to manual smoke).

## Locked decisions from the brainstorm

- Daily cadence; cost-bounded; reuses (user, ticker, trade_date) uniqueness.
- Global per-user opt-in via \`users.monitor_enabled\`.
- User-configurable HH:MM in IANA timezone.
- arq cron + due-users query (no denormalized next_fire_at column).
- \`Run.triggered_by\` enum ('manual' default | 'monitor') — backfills existing rows.
- Inline \`MonitorSection\` at top of \`/watchlist\` (no /settings page).

## Test plan

- [x] Server: 23 new tests; full suite passes
- [x] Migration up + down round-trip clean
- [x] Cross-session persistence test catches missing-commit regressions (Wave 5.1 pattern carried forward)
- [x] \`npm run build\` clean
- [x] 4 Playwright e2e tests (3 active + 1 skipped); CI dispatch will exercise the active ones
- [ ] Pre-merge: workflow dispatch against PR branch
- [ ] Post-merge: manual browser smoke
  - Enable on /watchlist → toggle visible → reload preserves
  - Set briefing time to "now + ~5min" in local TZ; wait for cron → row appears in /history with Monitor badge
  - Disable → reload preserves disabled state but server retains time+tz

## Followup queue (Wave 5.3+)

- 5.3 Signals feed UI — dedicated "what changed today" view aggregating triggered_by='monitor' runs by signal strength.
- 5.4 Notifications — email/push when a strong-signal run lands.
- Per-ticker opt-in (watchlist_items.monitor boolean).
- Cost cap / budget guards.
- Event-driven re-runs on price moves or news.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

Expected: PR URL printed.

- [ ] **Step 2: Pre-merge workflow dispatch**

```bash
gh workflow run deploy.yml --repo erikgunawans/TradingAgents --ref feature/monitor
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: build api, build web, deploy to VM all green. If ghcr.io flake hits, re-dispatch.

- [ ] **Step 3: Post-deploy smoke**

```bash
curl -fsS -o /dev/null -w "https://tradix.axiara.ai/login -> %{http_code}\n" https://tradix.axiara.ai/login
curl -fsS -o /dev/null -w "https://tradix.axiara.ai/watchlist (unauthed) -> %{http_code} -> %{redirect_url}\n" https://tradix.axiara.ai/watchlist
curl -fsS https://tradix.axiara.ai/api/auth/providers | python3 -c "import json, sys; print('providers:', list(json.load(sys.stdin).keys()))"
```

Expected: /login = 200, /watchlist = 307 → /api/auth/signin (auth gate unchanged), providers = ['github', 'google'].

- [ ] **Step 4: Merge**

```bash
PR_NUM=$(gh pr list --repo erikgunawans/TradingAgents --head feature/monitor --json number --jq '.[0].number')
gh pr merge $PR_NUM --merge --repo erikgunawans/TradingAgents
sleep 8
RUN_ID=$(gh run list --repo erikgunawans/TradingAgents --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo erikgunawans/TradingAgents --exit-status
```

Expected: merge succeeds, auto-deploy on main green, alembic upgrade head runs migration e4f5a6b7c8d9 during api container restart.

- [ ] **Step 5: Sync local + cleanup**

```bash
git -C /Users/erikgunawansupriatna/TradingAgents checkout main
git -C /Users/erikgunawansupriatna/TradingAgents pull fork main
git -C /Users/erikgunawansupriatna/TradingAgents branch -d feature/monitor
```

- [ ] **Step 6: Browser smoke**

Open `https://tradix.axiara.ai/watchlist` (signed in). Verify:

1. Daily monitor section visible at top of /watchlist.
2. Click **Enable** — section transitions to ON with time picker, tz input, "Next briefing in Xh Ym" countdown.
3. Change briefing time to ~5 minutes from now in local TZ. Wait. Within 5–20 minutes a run should appear in /history with the `Monitor` badge.
4. Visit `/history` — confirm the badge renders next to the ticker name on the monitor-dispatched row.
5. Back on `/watchlist` — click **Disable**. Section returns to OFF state. Reload — disabled state persists.

---

## Acceptance criteria

Mapping back to design §8:

- [ ] Daily cadence achievable: cron tick spawns at-most-one set of runs per user per day → §4.2 + §4.3 of design (window math + DuplicateRunningError handling)
- [ ] Global per-user opt-in via `users.monitor_enabled` → Task 3 step 1-2
- [ ] User-configurable briefing time + IANA tz with validation → Task 3 step 5 (MonitorUpdate validator), step 8 (endpoint)
- [ ] `Run.triggered_by` enum populated correctly for monitor-dispatched runs → Task 3 step 3 + step 7
- [ ] Inline `MonitorSection` renders on `/watchlist` with toggle + time + tz + countdown → Task 5
- [ ] `Monitor` badge appears in `/history` for monitor-dispatched runs → Task 6
- [ ] Edge cases handled (missed ticks, DST, empty watchlist, in-flight disable) → Task 2 (16 monitor tests + 7 endpoint tests)
- [ ] Migration `e4f5a6b7c8d9` lands cleanly on prod and round-trips → Task 3 step 11 + Task 8 step 4

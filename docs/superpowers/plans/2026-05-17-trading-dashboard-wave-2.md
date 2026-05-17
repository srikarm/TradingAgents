# TradingAgents Dashboard — Wave 2 (Launch + Live Monitor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let signed-in users launch new analyses from the dashboard and watch them stream in real time. POST `/runs` enqueues a job to an out-of-process arq worker; the worker runs `TradingAgentsGraph.propagate()` against the user's namespace and writes reports + `message_tool.log` to disk. The frontend polls `GET /runs/{id}/tail` every 2 seconds and renders the appended log bytes as they appear.

**Architecture:** New `worker` Docker service (same image as `api`, different CMD) consumes arq jobs from Redis. The worker imports `TradingAgentsGraph` directly — to make that possible the Dockerfile's build context moves up to the repo root so both `tradingagents/` (root package) and `server/` (FastAPI app) install into the same image. A heartbeat `asyncio.create_task` runs alongside `propagate()` and writes `last_heartbeat_at` every 30s; a cron `orphan_sweeper` marks `running` rows older than 10 minutes as `failed`. The live monitor is plain HTTP polling — no websockets, no LangGraph callback wiring.

**Tech Stack:** arq 0.26+, Redis 7, asyncio (heartbeat loop), Next.js 15 (server actions for launch, client components for tail polling).

**Reference spec:** `docs/superpowers/specs/2026-05-17-trading-dashboard-design.md` — Section 5.2 (Launch + monitor flow) and Section 6 (Error handling).

**Builds on:** Wave 1 plan `docs/superpowers/plans/2026-05-17-trading-dashboard-wave-1.md`. Wave 1 must be merged before Wave 2 starts.

---

## File Structure

```
TradingAgents/
├── Dockerfile                                   # NEW: top-level, builds both
│                                                # tradingagents/ + server/ into one image
├── server/
│   ├── pyproject.toml                           # MODIFY: add arq, redis; path-dep on root
│   ├── app/
│   │   ├── config.py                            # MODIFY: REDIS_URL, LLM env defaults,
│   │   │                                        #         HEARTBEAT_INTERVAL_SECONDS,
│   │   │                                        #         ORPHAN_THRESHOLD_SECONDS
│   │   ├── schemas/
│   │   │   └── run.py                           # MODIFY: add RunCreate, RunTailOut
│   │   ├── routers/
│   │   │   └── runs.py                          # MODIFY: add POST /, GET /{id}/tail
│   │   ├── services/
│   │   │   ├── redis_pool.py                    # NEW: arq RedisSettings + pool helper
│   │   │   ├── run_dispatcher.py                # NEW: validates + creates Run + enqueues
│   │   │   └── log_tailer.py                    # NEW: byte-offset file read
│   │   └── workers/
│   │       ├── __init__.py                      # NEW: empty
│   │       ├── worker.py                        # NEW: arq WorkerSettings entrypoint
│   │       └── tasks.py                         # NEW: run_propagate + orphan_sweeper
│   └── tests/
│       ├── test_redis_pool.py                   # NEW
│       ├── test_run_dispatcher.py               # NEW
│       ├── test_log_tailer.py                   # NEW
│       ├── test_runs_create.py                  # NEW: POST /runs integration
│       ├── test_runs_tail.py                    # NEW: GET /runs/{id}/tail integration
│       ├── test_tasks.py                        # NEW: worker tasks (stubbed graph)
│       └── test_orphan_sweeper.py               # NEW
├── web/
│   ├── lib/
│   │   ├── types.ts                             # MODIFY: add RunCreate, RunTailOut,
│   │   │                                        #         LlmConfig, AnalystKey
│   │   └── api.ts                               # MODIFY: add createRun, tailRun
│   ├── components/
│   │   ├── Nav.tsx                              # MODIFY: add Launch + Live links
│   │   ├── LaunchForm.tsx                       # NEW: client form
│   │   └── LiveLogStream.tsx                    # NEW: client component, polls tail
│   ├── app/
│   │   ├── launch/
│   │   │   ├── page.tsx                         # NEW: launch page (RSC wrapper)
│   │   │   └── actions.ts                       # NEW: server action POST /runs
│   │   └── live/
│   │       ├── page.tsx                         # NEW: list of running + recent runs
│   │       └── [runId]/page.tsx                 # NEW: live monitor for one run
│   └── tests/e2e/
│       └── launch.spec.ts                       # NEW: e2e launch + observe flow
└── docker-compose.yml                           # MODIFY: add redis + worker services
```

**Boundary rules:**
- `server/app/workers/` is the ONLY place that imports from `tradingagents/`.
- `server/app/routers/runs.py` never imports anything from `workers/` directly — it enqueues by name (`"run_propagate"`) via `redis_pool`.
- The frontend `web/` still never imports from `tradingagents/` or `server/`.

---

## Conventions

- Same as Wave 1: TDD, one commit per task, `cd server && uv run pytest -q` for server tests.
- Worker tests use a **stub `TradingAgentsGraph`** that writes fixture markdown + log content — never invoke real LLMs in CI.
- All new env vars go through `app/config.py` Settings — no `os.environ.get()` scattered in modules.
- Run all tests after each task (not just the one just-added) to catch regressions early.

---

## Task 1: Add arq + redis dependencies; make root `tradingagents` importable

**Files:**
- Modify: `server/pyproject.toml`
- Create: `Dockerfile` (at repo root — replaces `server/Dockerfile`'s context)
- Modify: `docker-compose.yml` (just `api.build` block — full updates in Task 17)
- Delete: `server/Dockerfile`

The worker needs to `from tradingagents.graph.trading_graph import TradingAgentsGraph`. The Wave 1 image only contained `server/`. We move to a unified top-level Dockerfile that installs the root `tradingagents` package and the `server` app into the same image.

- [ ] **Step 1: Add deps to `server/pyproject.toml`**

Append `"arq>=0.26"` and `"redis>=5.2"` to the `dependencies` list. The full updated `dependencies`:

```toml
dependencies = [
    "fastapi>=0.118",
    "uvicorn[standard]>=0.32",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "aiosqlite>=0.20",
    "alembic>=1.14",
    "pydantic-settings>=2.6",
    "pyjwt>=2.9",
    "python-multipart>=0.0.18",
    "httpx>=0.28",
    "arq>=0.26",
    "redis>=5.2",
]
```

Run `cd server && uv sync` to refresh the lockfile.

- [ ] **Step 2: Write a quick smoke test that the root package imports from inside `server/`**

Create `server/tests/test_root_package_import.py`:

```python
def test_can_import_tradingagents_graph():
    """The worker needs to import from the root tradingagents package.

    This test only passes if the server's environment has the root
    tradingagents package installed (via path-dep in pyproject.toml).
    """
    from tradingagents.default_config import DEFAULT_CONFIG  # noqa: F401
```

Run it; expect failure (`ModuleNotFoundError: No module named 'tradingagents'`).

```bash
cd server && uv run pytest tests/test_root_package_import.py -v
```

- [ ] **Step 3: Add a tool-uv source for the root tradingagents package**

Edit `server/pyproject.toml`. Append at the bottom:

```toml
[tool.uv.sources]
tradingagents = { path = "..", editable = true }
```

Then add `tradingagents` to the dependencies list:

```toml
dependencies = [
    # ... all existing deps ...
    "tradingagents",
]
```

Run `cd server && uv sync` again.

- [ ] **Step 4: Re-run the smoke test; expect pass**

```bash
cd server && uv run pytest tests/test_root_package_import.py -v
```

Expected: 1 passed. Full suite should still be all green: `cd server && uv run pytest -q` → 59 passed.

- [ ] **Step 5: Create the new top-level `Dockerfile`**

Create `/Users/erikgunawansupriatna/TradingAgents/Dockerfile`:

```dockerfile
# Unified image for the dashboard API + arq worker.
# Build context is the repo root so we can install both the root
# `tradingagents` package and the `server` app into the same image.

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy the root tradingagents package (needed by the worker)
COPY pyproject.toml requirements.txt ./
COPY tradingagents ./tradingagents

# Copy the server app and sync its deps (which include path-dep on ..)
COPY server ./server
WORKDIR /app/server
RUN uv sync --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 6: Delete the old `server/Dockerfile`**

```bash
rm server/Dockerfile
```

- [ ] **Step 7: Update `docker-compose.yml` `api` build block**

Find the `api:` service in `docker-compose.yml`. Change:

```yaml
  api:
    build: ./server
```

To:

```yaml
  api:
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /app/server
```

(Note: the rest of the `api` block — environment, depends_on, ports, command — stays unchanged. The worker service gets added in Task 11.)

- [ ] **Step 8: Build the image to verify it works**

```bash
docker compose build api
```

Expected: build succeeds. Image includes both `/app/tradingagents/` and `/app/server/`.

- [ ] **Step 9: Commit**

```bash
git add server/pyproject.toml server/uv.lock server/tests/test_root_package_import.py Dockerfile docker-compose.yml
git rm server/Dockerfile
git commit -m "chore(server): unify dockerfile for api+worker, add arq+redis deps"
```

---

## Task 2: Extend Settings with REDIS_URL, LLM defaults, heartbeat config

**Files:**
- Modify: `server/app/config.py`
- Modify: `server/tests/test_config.py`

- [ ] **Step 1: Write failing tests** — append to `server/tests/test_config.py`:

```python
def test_settings_reads_redis_and_worker_config(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "10")
    monkeypatch.setenv("ORPHAN_THRESHOLD_SECONDS", "300")
    s = Settings()
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.heartbeat_interval_seconds == 10
    assert s.orphan_threshold_seconds == 300


def test_settings_has_llm_provider_defaults(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    s = Settings()
    # Defaults — worker uses these if launch form doesn't override
    assert s.default_llm_provider == "openai"
    assert s.default_deep_think_llm.startswith("gpt-")
    assert s.default_quick_think_llm.startswith("gpt-")
```

Run; expect failures (AttributeError on the new fields).

- [ ] **Step 2: Update `server/app/config.py`** — replace the `Settings` class with:

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nextauth_secret: str
    database_url: str
    dashboard_data_dir: Path
    legacy_results_dir: Path | None = None
    jwt_algorithm: str = "HS256"
    jwt_audience: str | None = None
    max_tail_bytes: int = 64 * 1024

    # Wave 2
    redis_url: str = "redis://localhost:6379/0"
    heartbeat_interval_seconds: int = 30
    orphan_threshold_seconds: int = 600  # 10 minutes
    orphan_sweeper_interval_seconds: int = 300  # 5 minutes
    default_llm_provider: str = "openai"
    default_deep_think_llm: str = "gpt-5.4"
    default_quick_think_llm: str = "gpt-5.4-mini"
    default_max_debate_rounds: int = 1
    default_max_risk_discuss_rounds: int = 1

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3: Run; expect pass**

```bash
cd server && uv run pytest tests/test_config.py -v
```

Expected: 4 passed (2 from Wave 1 + 2 new).

- [ ] **Step 4: Commit**

```bash
git add server/app/config.py server/tests/test_config.py
git commit -m "feat(server): add redis + worker + llm-defaults settings"
```

---

## Task 3: Redis pool helper

**Files:**
- Create: `server/app/services/redis_pool.py`
- Create: `server/tests/test_redis_pool.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_redis_pool.py`:

```python
import pytest

from app.services.redis_pool import get_redis_settings


def test_redis_settings_parses_url(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("REDIS_URL", "redis://my-redis:6380/2")
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_redis_settings()
    assert settings.host == "my-redis"
    assert settings.port == 6380
    assert settings.database == 2


def test_redis_settings_defaults_to_localhost(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    monkeypatch.delenv("REDIS_URL", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_redis_settings()
    assert settings.host == "localhost"
    assert settings.port == 6379
    assert settings.database == 0
```

Run; expect ImportError.

- [ ] **Step 2: Implement `server/app/services/redis_pool.py`**

```python
"""arq Redis settings + connection pool helper.

The api process (enqueueing jobs) and the worker process (consuming them)
both share these settings.
"""

from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings


def get_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into arq's RedisSettings."""
    raw = get_settings().redis_url
    parsed = urlparse(raw)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )


async def get_redis_pool() -> ArqRedis:
    """Open a new arq pool. Caller is responsible for `.close()`."""
    return await create_pool(get_redis_settings())
```

- [ ] **Step 3: Run; expect 2 passed**

```bash
cd server && uv run pytest tests/test_redis_pool.py -v
```

- [ ] **Step 4: Commit**

```bash
git add server/app/services/redis_pool.py server/tests/test_redis_pool.py
git commit -m "feat(server): add arq redis pool helper"
```

---

## Task 4: Log tailer service

**Files:**
- Create: `server/app/services/log_tailer.py`
- Create: `server/tests/test_log_tailer.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_log_tailer.py`:

```python
from pathlib import Path

import pytest

from app.services.log_tailer import TailResult, tail_log


def test_tail_returns_empty_when_file_missing(tmp_path: Path):
    result = tail_log(tmp_path / "missing.log", since=0, max_bytes=1024)
    assert result == TailResult(content="", next_offset=0)


def test_tail_returns_full_content_from_offset_zero(tmp_path: Path):
    log = tmp_path / "msg.log"
    log.write_text("line one\nline two\n")
    result = tail_log(log, since=0, max_bytes=1024)
    assert result.content == "line one\nline two\n"
    assert result.next_offset == len(b"line one\nline two\n")


def test_tail_returns_only_appended_bytes(tmp_path: Path):
    log = tmp_path / "msg.log"
    log.write_text("first\n")
    r1 = tail_log(log, since=0, max_bytes=1024)
    log.write_text("first\nsecond\n")
    r2 = tail_log(log, since=r1.next_offset, max_bytes=1024)
    assert r2.content == "second\n"
    assert r2.next_offset == len(b"first\nsecond\n")


def test_tail_caps_at_max_bytes(tmp_path: Path):
    log = tmp_path / "msg.log"
    log.write_bytes(b"x" * 5000)
    result = tail_log(log, since=0, max_bytes=1024)
    assert len(result.content.encode("utf-8")) == 1024
    assert result.next_offset == 1024


def test_tail_resets_when_since_exceeds_size(tmp_path: Path):
    """If the log was rotated/truncated and `since` is past end of file,
    return everything from byte 0 instead of an empty response."""
    log = tmp_path / "msg.log"
    log.write_text("fresh\n")
    result = tail_log(log, since=10_000, max_bytes=1024)
    assert result.content == "fresh\n"
    assert result.next_offset == len(b"fresh\n")
```

Run; expect ImportError.

- [ ] **Step 2: Implement `server/app/services/log_tailer.py`**

```python
"""Safe byte-offset read of a worker's message_tool.log file.

The caller is responsible for ensuring the path is rooted inside the user
namespace (passed through `user_root`). This module does not re-validate
the path — it just performs the read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TailResult:
    content: str
    next_offset: int


def tail_log(path: Path, *, since: int, max_bytes: int) -> TailResult:
    """Return bytes from `path` starting at offset `since`, capped at `max_bytes`."""
    if not path.is_file():
        return TailResult(content="", next_offset=0)
    size = path.stat().st_size
    # If the log was truncated and `since` is past the new end, restart at 0.
    if since > size:
        since = 0
    end = min(since + max_bytes, size)
    with path.open("rb") as f:
        f.seek(since)
        data = f.read(end - since)
    return TailResult(content=data.decode("utf-8", errors="replace"), next_offset=end)
```

- [ ] **Step 3: Run; expect 5 passed**

```bash
cd server && uv run pytest tests/test_log_tailer.py -v
```

- [ ] **Step 4: Commit**

```bash
git add server/app/services/log_tailer.py server/tests/test_log_tailer.py
git commit -m "feat(server): add log_tailer service with byte-offset reads"
```

---

## Task 5: RunCreate / RunTailOut schemas

**Files:**
- Modify: `server/app/schemas/run.py`

- [ ] **Step 1: Append to `server/app/schemas/run.py`**

```python
from pydantic import Field


class RunCreate(BaseModel):
    """Request body for POST /runs."""

    ticker: str = Field(min_length=1, max_length=12)
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"],
        max_length=4,
    )
    llm_provider: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None
    asset_type: str = "stock"


class RunTailOut(BaseModel):
    """Response from GET /runs/{id}/tail."""

    content: str
    next_offset: int
    status: str
```

(Don't modify existing classes — only append.)

- [ ] **Step 2: Sanity check the module still imports**

```bash
cd server && uv run python -c "from app.schemas.run import RunCreate, RunTailOut; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add server/app/schemas/run.py
git commit -m "feat(server): add RunCreate and RunTailOut schemas"
```

---

## Task 6: Run dispatcher service

The dispatcher is the bridge between the HTTP layer and the queue: it validates the request, builds the per-user results path, inserts a `Run` row in status `queued`, and enqueues `run_propagate`.

**Files:**
- Create: `server/app/services/run_dispatcher.py`
- Create: `server/tests/test_run_dispatcher.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_run_dispatcher.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User
from app.schemas.run import RunCreate
from app.services.run_dispatcher import (
    DuplicateRunningError,
    dispatch_run,
)


class FakePool:
    def __init__(self):
        self.enqueued: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name: str, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return object()


@pytest.mark.asyncio
async def test_dispatch_run_creates_row_and_enqueues(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-d"))
    await db_session.flush()
    pool = FakePool()

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    run = await dispatch_run(
        session=db_session,
        pool=pool,
        user_id=uid,
        dashboard_dir=tmp_path,
        body=body,
    )

    assert run.user_id == uid
    assert run.ticker == "NVDA"
    assert run.status is RunStatus.QUEUED
    assert run.results_path.startswith(str(tmp_path))
    assert len(pool.enqueued) == 1
    name, args, _ = pool.enqueued[0]
    assert name == "run_propagate"
    assert args[0] == str(run.id)


@pytest.mark.asyncio
async def test_dispatch_run_uppercases_ticker(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-u"))
    await db_session.flush()
    body = RunCreate(ticker="nvda", trade_date="2024-05-10")
    run = await dispatch_run(
        session=db_session,
        pool=FakePool(),
        user_id=uid,
        dashboard_dir=tmp_path,
        body=body,
    )
    assert run.ticker == "NVDA"


@pytest.mark.asyncio
async def test_dispatch_run_rejects_duplicate_running(db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-x"))
    db_session.add(
        Run(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.RUNNING,
            results_path="x",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    with pytest.raises(DuplicateRunningError):
        await dispatch_run(
            session=db_session,
            pool=FakePool(),
            user_id=uid,
            dashboard_dir=tmp_path,
            body=body,
        )


@pytest.mark.asyncio
async def test_dispatch_run_allows_relaunch_of_completed(db_session, tmp_path):
    """A succeeded or failed run for the same ticker+date doesn't block re-launch."""
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-r"))
    db_session.add(
        Run(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED,
            results_path="x",
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    await db_session.flush()

    body = RunCreate(ticker="NVDA", trade_date="2024-05-10")
    run = await dispatch_run(
        session=db_session,
        pool=FakePool(),
        user_id=uid,
        dashboard_dir=tmp_path,
        body=body,
    )
    assert run.status is RunStatus.QUEUED
```

Run; expect ImportError.

- [ ] **Step 2: Implement `server/app/services/run_dispatcher.py`**

```python
"""Bridge between POST /runs and the arq queue.

Validates the request, builds a per-user results path via user_root,
inserts a Run row in 'queued' status, and enqueues run_propagate.
Rejects launches that collide with an already-running run for the same
(user, ticker, date).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run, RunStatus
from app.schemas.run import RunCreate
from app.services.user_root import user_run_dir


class _PoolProto(Protocol):
    async def enqueue_job(self, name: str, *args, **kwargs): ...


class DuplicateRunningError(Exception):
    """A run is already queued or running for this (user, ticker, date)."""

    def __init__(self, existing_id: uuid.UUID) -> None:
        self.existing_id = existing_id
        super().__init__(f"duplicate running run: {existing_id}")


async def dispatch_run(
    *,
    session: AsyncSession,
    pool: _PoolProto,
    user_id: uuid.UUID,
    dashboard_dir: Path,
    body: RunCreate,
) -> Run:
    ticker = body.ticker.upper()
    trade_date = body.trade_date

    # Reject collision with active runs.
    blocking = (
        await session.execute(
            select(Run).where(
                Run.user_id == user_id,
                Run.ticker == ticker,
                Run.trade_date == trade_date,
                Run.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            )
        )
    ).scalar_one_or_none()
    if blocking is not None:
        raise DuplicateRunningError(blocking.id)

    target = user_run_dir(dashboard_dir, str(user_id), ticker, trade_date)
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=trade_date,
        status=RunStatus.QUEUED,
        results_path=str(target),
        created_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()

    await pool.enqueue_job(
        "run_propagate",
        str(run.id),
        _job_id=f"run_{run.id}",
    )
    return run
```

- [ ] **Step 3: Run; expect 4 passed**

```bash
cd server && uv run pytest tests/test_run_dispatcher.py -v
```

- [ ] **Step 4: Commit**

```bash
git add server/app/services/run_dispatcher.py server/tests/test_run_dispatcher.py
git commit -m "feat(server): add run dispatcher service"
```

---

## Task 7: Worker task `run_propagate` (with stubbed TradingAgentsGraph for tests)

**Files:**
- Create: `server/app/workers/__init__.py` (empty)
- Create: `server/app/workers/tasks.py`
- Create: `server/tests/test_tasks.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_tasks.py`:

```python
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User
from app.workers import tasks as worker_tasks


class StubGraph:
    """Stand-in for TradingAgentsGraph. Writes a fake report + log."""

    def __init__(self, *, selected_analysts, config, **_kwargs):
        self.config = config
        self.selected_analysts = selected_analysts

    def propagate(self, company_name, trade_date, asset_type="stock"):
        results = Path(self.config["results_dir"]) / company_name / trade_date
        (results / "reports" / "1_analysts").mkdir(parents=True, exist_ok=True)
        (results / "reports" / "1_analysts" / "market.md").write_text("# market")
        (results / "reports" / "final_trade_decision.md").write_text("# final\n\n**Rating**: Buy")
        log = results / "message_tool.log"
        log.write_text("step 1\nstep 2\n")
        return {"market_report": "# market", "final_trade_decision": "# final"}, "Buy"


class FailingGraph(StubGraph):
    def propagate(self, *a, **kw):
        raise RuntimeError("simulated llm error")


@pytest.mark.asyncio
async def test_run_propagate_marks_succeeded(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: StubGraph(**kw))
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        lambda: _factory_yielding(db_session))

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-w"))
    run_id = uuid.uuid4()
    db_session.add(
        Run(
            id=run_id,
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.QUEUED,
            results_path=str(tmp_path / "NVDA" / "2024-05-10"),
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    await worker_tasks.run_propagate({"redis": MagicMock()}, str(run_id))
    await db_session.flush()
    found = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert found.status is RunStatus.SUCCEEDED
    assert found.final_rating == "Buy"
    assert found.completed_at is not None


@pytest.mark.asyncio
async def test_run_propagate_marks_failed_on_exception(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: FailingGraph(**kw))
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        lambda: _factory_yielding(db_session))

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-w2"))
    run_id = uuid.uuid4()
    db_session.add(
        Run(
            id=run_id,
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.QUEUED,
            results_path=str(tmp_path / "NVDA" / "2024-05-10"),
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    await worker_tasks.run_propagate({"redis": MagicMock()}, str(run_id))
    await db_session.flush()
    found = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert found.status is RunStatus.FAILED
    assert found.error_summary is not None
    assert "simulated llm error" in found.error_summary


def _factory_yielding(session):
    """Returns a callable that, when called, returns an async-context-manager
    yielding the supplied session. Mimics async_sessionmaker."""
    class _Wrapper:
        async def __aenter__(self_):
            return session

        async def __aexit__(self_, *exc):
            return False

    def _factory():
        return _Wrapper()

    return _factory
```

Run; expect ImportError.

- [ ] **Step 2: Implement `server/app/workers/tasks.py`**

```python
"""arq worker tasks.

This module is the ONLY place that imports from the root tradingagents
package. The api process never imports from here directly — it enqueues
by name via the arq pool.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session_factory
from app.models.run import Run, RunStatus

logger = logging.getLogger(__name__)


def _graph_factory(**kwargs):
    """Indirection so tests can patch in a stub TradingAgentsGraph."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(**kwargs)


def _session_factory_for_worker():
    """Indirection for tests to inject a session factory."""
    return get_session_factory()()


def _build_config(run: Run) -> dict:
    """Build the TradingAgentsGraph config dict for a given Run."""
    from tradingagents.default_config import DEFAULT_CONFIG

    settings = get_settings()
    cfg = DEFAULT_CONFIG.copy()
    user_dir = Path(settings.dashboard_data_dir) / "users" / str(run.user_id)
    cfg["results_dir"] = str(user_dir)
    cfg["data_cache_dir"] = str(user_dir / "cache")
    cfg["memory_log_path"] = str(user_dir / "memory" / "trading_memory.md")
    cfg["llm_provider"] = settings.default_llm_provider
    cfg["deep_think_llm"] = settings.default_deep_think_llm
    cfg["quick_think_llm"] = settings.default_quick_think_llm
    cfg["max_debate_rounds"] = settings.default_max_debate_rounds
    cfg["max_risk_discuss_rounds"] = settings.default_max_risk_discuss_rounds
    return cfg


async def _heartbeat_loop(session_factory, run_id: uuid.UUID, interval: int) -> None:
    """Update Run.last_heartbeat_at every `interval` seconds until cancelled."""
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
        try:
            async with session_factory() as session:
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(last_heartbeat_at=datetime.now(timezone.utc))
                )
                await session.commit()
        except Exception:  # noqa: BLE001 — heartbeat failures must not kill the worker
            logger.exception("heartbeat update failed for run_id=%s", run_id)


async def run_propagate(ctx: dict, run_id_str: str) -> None:
    """Main worker task. Marks run as running, executes propagate, marks done."""
    run_id = uuid.UUID(run_id_str)
    settings = get_settings()

    session_factory = _session_factory_for_worker
    # First transaction: mark running.
    async with session_factory() as session:
        run = (
            await session.execute(select(Run).where(Run.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            logger.error("run_propagate: run %s not found", run_id)
            return
        run.status = RunStatus.RUNNING
        run.last_heartbeat_at = datetime.now(timezone.utc)
        await session.commit()
        ticker = run.ticker
        trade_date = run.trade_date
        config = _build_config(run)

    heartbeat = asyncio.create_task(
        _heartbeat_loop(session_factory, run_id, settings.heartbeat_interval_seconds)
    )

    error_summary: str | None = None
    error_detail: str | None = None
    final_rating: str | None = None
    try:
        graph = _graph_factory(
            selected_analysts=["market", "social", "news", "fundamentals"],
            config=config,
        )
        # propagate() may be sync — run in default executor so we don't block the
        # event loop and the heartbeat keeps firing.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: graph.propagate(ticker, trade_date)
        )
        # propagate() returns (final_state_dict, decision_str) in real impl
        if isinstance(result, tuple) and len(result) == 2:
            final_rating = str(result[1]).split()[0] if result[1] else None
    except Exception as exc:  # noqa: BLE001
        import traceback

        error_summary = str(exc)[:500]
        error_detail = traceback.format_exc()[:8000]
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass

    # Second transaction: mark terminal.
    async with session_factory() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status=RunStatus.FAILED if error_summary else RunStatus.SUCCEEDED,
                final_rating=final_rating,
                completed_at=datetime.now(timezone.utc),
                error_summary=error_summary,
                error_detail=error_detail,
            )
        )
        await session.commit()
```

- [ ] **Step 3: Run; expect 2 passed**

```bash
cd server && uv run pytest tests/test_tasks.py -v
```

- [ ] **Step 4: Commit**

```bash
git add server/app/workers/__init__.py server/app/workers/tasks.py server/tests/test_tasks.py
git commit -m "feat(server): add run_propagate worker task"
```

---

## Task 8: Orphan sweeper cron task

**Files:**
- Modify: `server/app/workers/tasks.py` (append `orphan_sweeper`)
- Create: `server/tests/test_orphan_sweeper.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_orphan_sweeper.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User
from app.workers import tasks as worker_tasks


def _wrapper_factory(session):
    class _W:
        async def __aenter__(_self):
            return session

        async def __aexit__(_self, *exc):
            return False

    def _f():
        return _W()

    return _f


@pytest.mark.asyncio
async def test_orphan_sweeper_marks_stale_running_as_failed(db_session, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-o"))
    now = datetime.now(timezone.utc)
    stale_id = uuid.uuid4()
    fresh_id = uuid.uuid4()
    db_session.add(
        Run(
            id=stale_id, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
            status=RunStatus.RUNNING, results_path="x", created_at=now,
            last_heartbeat_at=now - timedelta(minutes=15),
        )
    )
    db_session.add(
        Run(
            id=fresh_id, user_id=uid, ticker="AAPL", trade_date="2024-05-10",
            status=RunStatus.RUNNING, results_path="x", created_at=now,
            last_heartbeat_at=now - timedelta(seconds=20),
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    stale = (await db_session.execute(select(Run).where(Run.id == stale_id))).scalar_one()
    fresh = (await db_session.execute(select(Run).where(Run.id == fresh_id))).scalar_one()
    assert stale.status is RunStatus.FAILED
    assert stale.error_summary == "worker_lost"
    assert fresh.status is RunStatus.RUNNING


@pytest.mark.asyncio
async def test_orphan_sweeper_ignores_terminal_runs(db_session, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _wrapper_factory(db_session))
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-o2"))
    rid = uuid.uuid4()
    db_session.add(
        Run(
            id=rid, user_id=uid, ticker="NVDA", trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED, results_path="x",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    await db_session.flush()

    await worker_tasks.orphan_sweeper({"redis": None})
    await db_session.flush()
    run = (await db_session.execute(select(Run).where(Run.id == rid))).scalar_one()
    assert run.status is RunStatus.SUCCEEDED  # untouched
```

Run; expect AttributeError (no `orphan_sweeper`).

- [ ] **Step 2: Append `orphan_sweeper` to `server/app/workers/tasks.py`**

```python
async def orphan_sweeper(ctx: dict) -> None:
    """Cron: mark `running` rows whose heartbeat is older than threshold as failed."""
    settings = get_settings()
    threshold = datetime.now(timezone.utc) - timedelta(
        seconds=settings.orphan_threshold_seconds
    )
    async with _session_factory_for_worker() as session:
        result = await session.execute(
            update(Run)
            .where(
                Run.status == RunStatus.RUNNING,
                Run.last_heartbeat_at < threshold,
            )
            .values(
                status=RunStatus.FAILED,
                error_summary="worker_lost",
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        logger.info("orphan_sweeper: marked %d run(s) failed", result.rowcount)
```

Add `timedelta` to the existing `from datetime import ...` line at the top of `tasks.py`.

- [ ] **Step 3: Run; expect 2 passed**

```bash
cd server && uv run pytest tests/test_orphan_sweeper.py -v
```

- [ ] **Step 4: Commit**

```bash
git add server/app/workers/tasks.py server/tests/test_orphan_sweeper.py
git commit -m "feat(server): add orphan_sweeper cron task"
```

---

## Task 9: arq WorkerSettings entrypoint

**Files:**
- Create: `server/app/workers/worker.py`

- [ ] **Step 1: Implement `server/app/workers/worker.py`**

```python
"""arq worker entrypoint.

Run with: ``uv run arq app.workers.worker.WorkerSettings``
"""

from __future__ import annotations

from arq.cron import cron

from app.config import get_settings
from app.services.redis_pool import get_redis_settings
from app.workers.tasks import orphan_sweeper, run_propagate


class WorkerSettings:
    functions = [run_propagate]
    cron_jobs = [
        cron(
            orphan_sweeper,
            minute=set(range(0, 60, 5)),  # every 5 minutes
        )
    ]
    redis_settings = get_redis_settings()
    max_jobs = 1  # v1: one run at a time per worker process
    job_timeout = 60 * 60  # 1 hour cap on a single propagate
```

- [ ] **Step 2: Sanity check it loads**

```bash
cd server && NEXTAUTH_SECRET=x DATABASE_URL=sqlite+aiosqlite:///:memory: DASHBOARD_DATA_DIR=/tmp/x \
  uv run python -c "from app.workers.worker import WorkerSettings; print(WorkerSettings.functions, WorkerSettings.cron_jobs)"
```

Expected: prints the list with `run_propagate` and a cron entry.

- [ ] **Step 3: Commit**

```bash
git add server/app/workers/worker.py
git commit -m "feat(server): add arq worker entrypoint"
```

---

## Task 10: POST /runs endpoint

**Files:**
- Modify: `server/app/routers/runs.py` (append POST handler)
- Modify: `server/app/main.py` (no changes — runs_router already mounted)
- Create: `server/tests/test_runs_create.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_runs_create.py`:

```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.user import User
from tests.conftest import make_jwt


class FakePool:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return object()

    async def close(self): pass


@pytest.fixture
def fake_pool():
    return FakePool()


@pytest.fixture
def client(db_session, fake_pool, monkeypatch):
    async def _override_db():
        yield db_session

    async def _override_pool():
        yield fake_pool

    from app.routers.runs import get_pool
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_pool] = _override_pool
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_runs_creates_and_enqueues(client, db_session, fake_pool, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    db_session.add(User(id=uuid.uuid4(), github_id="gh-p"))
    await db_session.flush()

    async with client as c:
        r = await c.post(
            "/runs",
            json={"ticker": "NVDA", "trade_date": "2024-05-10"},
            headers={"Authorization": f"Bearer {make_jwt('gh-p')}"},
        )
    assert r.status_code == 202
    assert "run_id" in r.json()
    assert len(fake_pool.enqueued) == 1


@pytest.mark.asyncio
async def test_post_runs_409_on_duplicate_running(client, db_session, fake_pool, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from app.models.run import Run, RunStatus

    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-q"))
    db_session.add(
        Run(
            id=uuid.uuid4(),
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.RUNNING,
            results_path="x",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    async with client as c:
        r = await c.post(
            "/runs",
            json={"ticker": "NVDA", "trade_date": "2024-05-10"},
            headers={"Authorization": f"Bearer {make_jwt('gh-q')}"},
        )
    assert r.status_code == 409
    assert "existing_run_id" in r.json()["detail"]


@pytest.mark.asyncio
async def test_post_runs_422_on_bad_ticker(client, db_session, fake_pool):
    async with client as c:
        r = await c.post(
            "/runs",
            json={"ticker": "", "trade_date": "2024-05-10"},
            headers={"Authorization": f"Bearer {make_jwt('gh-z')}"},
        )
    assert r.status_code == 422
```

Run; expect ImportError / 404.

- [ ] **Step 2: Append POST handler + `get_pool` dep to `server/app/routers/runs.py`**

Add these imports at the top of the file:

```python
from fastapi import Body, status as http_status
from app.config import get_settings
from app.schemas.run import RunCreate
from app.services.run_dispatcher import DuplicateRunningError, dispatch_run
from app.services.redis_pool import get_redis_pool
```

Add the `get_pool` dependency near the top of the module (after the imports, before the router):

```python
async def get_pool():
    """FastAPI dep yielding an arq pool. Closed after the request."""
    pool = await get_redis_pool()
    try:
        yield pool
    finally:
        await pool.close()
```

Append the POST handler:

```python
@router.post("", status_code=http_status.HTTP_202_ACCEPTED)
async def create_run(
    body: RunCreate = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pool=Depends(get_pool),
) -> dict:
    settings = get_settings()
    try:
        run = await dispatch_run(
            session=db,
            pool=pool,
            user_id=user.id,
            dashboard_dir=settings.dashboard_data_dir,
            body=body,
        )
    except DuplicateRunningError as e:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_running",
                "existing_run_id": str(e.existing_id),
            },
        )
    return {"run_id": str(run.id)}
```

- [ ] **Step 3: Run; expect 3 passed**

```bash
cd server && uv run pytest tests/test_runs_create.py -v
```

- [ ] **Step 4: Commit**

```bash
git add server/app/routers/runs.py server/tests/test_runs_create.py
git commit -m "feat(server): add POST /runs endpoint"
```

---

## Task 11: GET /runs/{id}/tail endpoint

**Files:**
- Modify: `server/app/routers/runs.py` (append tail handler)
- Create: `server/tests/test_runs_tail.py`

- [ ] **Step 1: Write failing test** — `server/tests/test_runs_tail.py`:

```python
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.run import Run, RunStatus
from app.models.user import User
from tests.conftest import make_jwt


@pytest.fixture
def client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


def _seed_run(db, *, user_id, status=RunStatus.RUNNING, results_path):
    rid = uuid.uuid4()
    db.add(
        Run(
            id=rid, user_id=user_id, ticker="NVDA", trade_date="2024-05-10",
            status=status, results_path=str(results_path),
            created_at=datetime.now(timezone.utc),
        )
    )
    return rid


@pytest.mark.asyncio
async def test_tail_returns_log_bytes(client, db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-t"))
    rdir = tmp_path / "NVDA" / "2024-05-10"
    rdir.mkdir(parents=True)
    (rdir / "message_tool.log").write_text("hello\n")
    rid = _seed_run(db_session, user_id=uid, results_path=rdir)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{rid}/tail?since=0",
            headers={"Authorization": f"Bearer {make_jwt('gh-t')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "hello\n"
    assert body["next_offset"] == len(b"hello\n")
    assert body["status"] == "running"


@pytest.mark.asyncio
async def test_tail_returns_empty_when_log_missing(client, db_session, tmp_path):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-tm"))
    rdir = tmp_path / "NVDA" / "2024-05-10"
    rdir.mkdir(parents=True)
    rid = _seed_run(db_session, user_id=uid, status=RunStatus.QUEUED, results_path=rdir)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{rid}/tail?since=0",
            headers={"Authorization": f"Bearer {make_jwt('gh-tm')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == ""
    assert body["next_offset"] == 0
    assert body["status"] == "queued"


@pytest.mark.asyncio
async def test_tail_404_for_other_users_run(client, db_session, tmp_path):
    me, other = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me, github_id="gh-me"))
    db_session.add(User(id=other, github_id="gh-other"))
    rdir = tmp_path / "AAPL" / "2024-05-10"
    rdir.mkdir(parents=True)
    rid = _seed_run(db_session, user_id=other, results_path=rdir)
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{rid}/tail?since=0",
            headers={"Authorization": f"Bearer {make_jwt('gh-me')}"},
        )
    assert r.status_code == 404
```

Run; expect 404 / ImportError.

- [ ] **Step 2: Append handler to `server/app/routers/runs.py`**

Add imports:

```python
from app.schemas.run import RunTailOut
from app.services.log_tailer import tail_log
```

Append handler (place AFTER the existing `get_run` handler):

```python
@router.get("/{run_id}/tail", response_model=RunTailOut)
async def tail_run(
    run_id: _uuid.UUID,
    since: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunTailOut:
    run = (
        await db.execute(
            select(Run).where(Run.id == run_id, Run.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    settings = get_settings()
    log_path = Path(run.results_path) / "message_tool.log"
    result = tail_log(log_path, since=since, max_bytes=settings.max_tail_bytes)
    return RunTailOut(
        content=result.content,
        next_offset=result.next_offset,
        status=run.status.value,
    )
```

Also add `from pathlib import Path` if not already imported at the top of the file.

- [ ] **Step 3: Run; expect 3 passed**

```bash
cd server && uv run pytest tests/test_runs_tail.py -v
```

Full suite: should be ~70+ passed now.

- [ ] **Step 4: Commit**

```bash
git add server/app/routers/runs.py server/tests/test_runs_tail.py
git commit -m "feat(server): add /runs/{id}/tail polling endpoint"
```

---

## Task 12: Frontend types + API client extensions

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Append to `web/lib/types.ts`**

```typescript
export type AnalystKey = "market" | "social" | "news" | "fundamentals";

export interface RunCreate {
  ticker: string;
  trade_date: string;
  analysts?: AnalystKey[];
  llm_provider?: string;
  deep_think_llm?: string;
  quick_think_llm?: string;
  asset_type?: "stock" | "crypto";
}

export interface RunTailOut {
  content: string;
  next_offset: number;
  status: RunStatus;
}
```

- [ ] **Step 2: Extend `web/lib/api.ts`**

Replace the file with:

```typescript
import { SignJWT } from "jose";
import { auth } from "@/lib/auth";
import type {
  RunCreate,
  RunDetailOut,
  RunListOut,
  RunTailOut,
  UserOut,
} from "@/lib/types";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

async function bearer(): Promise<string> {
  const session = await auth();
  if (!session?.user) throw new Error("unauthenticated");
  const sub = (session.user as { githubId?: string }).githubId;
  if (!sub) throw new Error("session missing githubId");
  const secret = new TextEncoder().encode(process.env.NEXTAUTH_SECRET!);
  const token = await new SignJWT({ email: session.user.email ?? null })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(sub)
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(secret);
  return `Bearer ${token}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`api ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      Authorization: await bearer(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`api ${path} failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => get<UserOut>("/me"),
  listRuns: (ticker?: string) =>
    get<RunListOut>(ticker ? `/runs?ticker=${encodeURIComponent(ticker)}` : "/runs"),
  getRun: (id: string) => get<RunDetailOut>(`/runs/${id}`),
  createRun: (body: RunCreate) => post<{ run_id: string }>("/runs", body),
  tailRun: (id: string, since: number) =>
    get<RunTailOut>(`/runs/${id}/tail?since=${since}`),
};
```

- [ ] **Step 3: Verify typecheck**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run typecheck
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add web/lib/types.ts web/lib/api.ts
git commit -m "feat(web): add createRun and tailRun client methods"
```

---

## Task 13: Launch page + form + server action

**Files:**
- Create: `web/components/LaunchForm.tsx`
- Create: `web/app/launch/actions.ts`
- Create: `web/app/launch/page.tsx`

- [ ] **Step 1: Create `web/app/launch/actions.ts`**

```typescript
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { AnalystKey } from "@/lib/types";

export type LaunchFormError =
  | { kind: "validation"; message: string }
  | { kind: "conflict"; existingRunId: string }
  | { kind: "unknown"; message: string };

export async function launchRunAction(formData: FormData): Promise<LaunchFormError | void> {
  const ticker = String(formData.get("ticker") ?? "").trim();
  const trade_date = String(formData.get("trade_date") ?? "").trim();
  if (!ticker || !trade_date) {
    return { kind: "validation", message: "Ticker and trade date are required." };
  }
  const analysts = (formData.getAll("analysts") as string[]).filter(
    (a): a is AnalystKey =>
      a === "market" || a === "social" || a === "news" || a === "fundamentals"
  );
  try {
    const { run_id } = await api.createRun({
      ticker,
      trade_date,
      analysts: analysts.length ? analysts : undefined,
    });
    redirect(`/live/${run_id}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("409")) {
      const match = msg.match(/"existing_run_id":\s*"([0-9a-f-]+)"/);
      if (match) return { kind: "conflict", existingRunId: match[1] };
    }
    return { kind: "unknown", message: msg };
  }
}
```

- [ ] **Step 2: Create `web/components/LaunchForm.tsx`**

```tsx
"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { launchRunAction, type LaunchFormError } from "@/app/launch/actions";

const ANALYSTS = [
  { key: "market", label: "Market" },
  { key: "social", label: "Social" },
  { key: "news", label: "News" },
  { key: "fundamentals", label: "Fundamentals" },
] as const;

export default function LaunchForm() {
  const [error, setError] = useState<LaunchFormError | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  const onSubmit = (fd: FormData) => {
    startTransition(async () => {
      const res = await launchRunAction(fd);
      if (res) setError(res);
    });
  };

  return (
    <form
      action={onSubmit}
      style={{ display: "grid", gap: 12, maxWidth: 400 }}
    >
      <label>
        Ticker
        <input
          name="ticker"
          required
          maxLength={12}
          placeholder="NVDA"
          style={{ padding: 8, width: "100%" }}
        />
      </label>
      <label>
        Trade date
        <input
          name="trade_date"
          type="date"
          required
          style={{ padding: 8, width: "100%" }}
        />
      </label>
      <fieldset style={{ border: "1px solid #e5e7eb", padding: 12, borderRadius: 6 }}>
        <legend>Analysts</legend>
        {ANALYSTS.map((a) => (
          <label key={a.key} style={{ display: "block", padding: "2px 0" }}>
            <input type="checkbox" name="analysts" value={a.key} defaultChecked />
            &nbsp;{a.label}
          </label>
        ))}
      </fieldset>
      <button
        type="submit"
        disabled={isPending}
        style={{
          padding: "10px 20px", background: "#2563eb", color: "#fff",
          border: "none", borderRadius: 6, cursor: isPending ? "wait" : "pointer",
        }}
      >
        {isPending ? "Launching..." : "Launch"}
      </button>
      {error && (
        <div style={{ color: "#dc2626", padding: 8, background: "#fef2f2", borderRadius: 6 }}>
          {error.kind === "conflict" ? (
            <>
              A run is already in progress for this ticker+date.{" "}
              <button
                type="button"
                onClick={() => router.push(`/live/${error.existingRunId}`)}
                style={{ textDecoration: "underline", background: "none", border: "none", color: "#dc2626", cursor: "pointer" }}
              >
                View running run
              </button>
            </>
          ) : (
            error.message
          )}
        </div>
      )}
    </form>
  );
}
```

- [ ] **Step 3: Create `web/app/launch/page.tsx`**

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import Nav from "@/components/Nav";
import LaunchForm from "@/components/LaunchForm";

export default async function LaunchPage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 800, margin: "0 auto" }}>
        <h1>Launch a new analysis</h1>
        <p style={{ color: "#6b7280", marginBottom: 24 }}>
          The worker uses LLM provider credentials configured on the server.
          Per-user keys land in a future release.
        </p>
        <LaunchForm />
      </main>
    </>
  );
}
```

- [ ] **Step 4: Verify typecheck + build**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run typecheck
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run build
```

Expected: zero errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/components/LaunchForm.tsx web/app/launch/
git commit -m "feat(web): add launch page with server action"
```

---

## Task 14: LiveLogStream client component

**Files:**
- Create: `web/components/LiveLogStream.tsx`

- [ ] **Step 1: Create `web/components/LiveLogStream.tsx`**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import type { RunStatus, RunTailOut } from "@/lib/types";

interface Props {
  runId: string;
  initialStatus: RunStatus;
  pollIntervalMs?: number;
}

export default function LiveLogStream({ runId, initialStatus, pollIntervalMs = 2000 }: Props) {
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<RunStatus>(initialStatus);
  const offsetRef = useRef(0);
  const scrollRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (status === "succeeded" || status === "failed") return;
    const ctl = new AbortController();
    let stopped = false;
    let backoffMs = pollIntervalMs;

    async function poll() {
      while (!stopped) {
        try {
          const res = await fetch(`/api/runs/${runId}/tail?since=${offsetRef.current}`, {
            signal: ctl.signal,
            cache: "no-store",
          });
          if (!res.ok) {
            backoffMs = Math.min(backoffMs * 2, 16000);
          } else {
            const data: RunTailOut = await res.json();
            offsetRef.current = data.next_offset;
            if (data.content) setContent((c) => c + data.content);
            setStatus(data.status);
            backoffMs = pollIntervalMs;
            if (data.status === "succeeded" || data.status === "failed") break;
          }
        } catch (e) {
          if (ctl.signal.aborted) return;
          backoffMs = Math.min(backoffMs * 2, 16000);
        }
        await new Promise((r) => setTimeout(r, backoffMs));
      }
    }

    poll();
    return () => {
      stopped = true;
      ctl.abort();
    };
  }, [runId, status, pollIntervalMs]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [content]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          display: "inline-block", width: 8, height: 8, borderRadius: "50%",
          background: status === "running" ? "#22c55e" :
                      status === "queued" ? "#f59e0b" :
                      status === "succeeded" ? "#2563eb" : "#dc2626",
          animation: status === "running" ? "pulse 1.5s infinite" : "none",
        }} />
        <strong style={{ textTransform: "uppercase", fontSize: 12 }}>{status}</strong>
      </div>
      <pre
        ref={scrollRef}
        style={{
          background: "#0f172a", color: "#e2e8f0",
          padding: 16, borderRadius: 8,
          maxHeight: 500, overflow: "auto",
          fontSize: 12, fontFamily: "ui-monospace, monospace",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}
      >
        {content || "(waiting for output...)"}
      </pre>
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.4 } }`}</style>
    </div>
  );
}
```

Note: This component polls `/api/runs/{runId}/tail` — a Next.js route that proxies to the FastAPI backend. We need that proxy route in the next task (Task 15) because the client can't call FastAPI directly (CORS + JWT minting both require server-side execution).

- [ ] **Step 2: Verify typecheck**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run typecheck
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add web/components/LiveLogStream.tsx
git commit -m "feat(web): add LiveLogStream polling component"
```

---

## Task 15: Tail proxy route + live monitor page

The client component polls `/api/runs/{id}/tail` — that's a Next.js route handler that calls the server-side `api.tailRun()` (which mints the JWT). The browser never sees the JWT directly.

**Files:**
- Create: `web/app/api/runs/[runId]/tail/route.ts`
- Create: `web/app/live/[runId]/page.tsx`
- Create: `web/app/live/page.tsx`

- [ ] **Step 1: Create proxy route `web/app/api/runs/[runId]/tail/route.ts`**

```typescript
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ runId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { runId } = await params;
  const since = Number(req.nextUrl.searchParams.get("since") ?? 0);
  try {
    const data = await api.tailRun(runId, since);
    return NextResponse.json(data);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("404")) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
```

- [ ] **Step 2: Create `web/app/live/[runId]/page.tsx`**

```tsx
import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RatingBadge from "@/components/RatingBadge";
import LiveLogStream from "@/components/LiveLogStream";

export default async function LiveRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { runId } = await params;
  let run;
  try {
    run = await api.getRun(runId);
  } catch {
    notFound();
  }
  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <h1 style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {run.ticker} · {run.trade_date} <RatingBadge rating={run.final_rating} />
        </h1>
        <LiveLogStream runId={run.id} initialStatus={run.status} />
        {(run.status === "succeeded" || run.status === "failed") && (
          <p style={{ marginTop: 16 }}>
            <a href={`/history/${run.id}`} style={{ color: "#2563eb" }}>
              View final reports →
            </a>
          </p>
        )}
        {run.error_summary && (
          <div style={{
            marginTop: 16, padding: 12, background: "#fef2f2",
            border: "1px solid #fecaca", borderRadius: 6, color: "#7f1d1d",
          }}>
            <strong>Error:</strong> {run.error_summary}
          </div>
        )}
      </main>
    </>
  );
}
```

- [ ] **Step 3: Create `web/app/live/page.tsx` (list of active + recent runs)**

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RunCard from "@/components/RunCard";

export default async function LivePage() {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { items } = await api.listRuns();
  const active = items.filter((r) => r.status === "queued" || r.status === "running");
  const recent = items.filter((r) => r.status === "succeeded" || r.status === "failed").slice(0, 10);

  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 800, margin: "0 auto" }}>
        <h1>Live runs</h1>
        <section style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 18, color: "#374151" }}>Active</h2>
          {active.length === 0 ? (
            <p style={{ color: "#6b7280" }}>
              No active runs. <a href="/launch" style={{ color: "#2563eb" }}>Launch one →</a>
            </p>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {active.map((r) => (
                <a key={r.id} href={`/live/${r.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                  <RunCard run={r} />
                </a>
              ))}
            </div>
          )}
        </section>
        <section>
          <h2 style={{ fontSize: 18, color: "#374151" }}>Recent</h2>
          <div style={{ display: "grid", gap: 12 }}>
            {recent.map((r) => <RunCard key={r.id} run={r} />)}
          </div>
        </section>
      </main>
    </>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run build
```

Expected: build succeeds, all new routes appear.

- [ ] **Step 5: Commit**

```bash
git add web/app/api/runs/ web/app/live/
git commit -m "feat(web): add live monitor page + tail proxy route"
```

---

## Task 16: Update Nav with Launch + Live links

**Files:**
- Modify: `web/components/Nav.tsx`

- [ ] **Step 1: Replace `web/components/Nav.tsx`**

```tsx
import Link from "next/link";

export default function Nav() {
  return (
    <nav style={{ padding: "12px 24px", borderBottom: "1px solid #e5e7eb",
                  display: "flex", gap: 16, alignItems: "center" }}>
      <strong>TradingAgents</strong>
      <Link href="/history">History</Link>
      <Link href="/live">Live</Link>
      <Link href="/launch">Launch</Link>
    </nav>
  );
}
```

- [ ] **Step 2: Verify typecheck**

```bash
cd web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run typecheck
```

- [ ] **Step 3: Commit**

```bash
git add web/components/Nav.tsx
git commit -m "feat(web): add Live and Launch links to nav"
```

---

## Task 17: docker-compose — add redis + worker services

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update `docker-compose.yml`**

Read the current file. Apply these changes:

1. Add a `redis` service (alongside `db`):

```yaml
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
```

2. Add `REDIS_URL` to `api.environment`:

```yaml
      REDIS_URL: redis://redis:6379/0
```

3. Add `redis` to `api.depends_on`:

```yaml
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
```

4. Add a new `worker` service (after `api`):

```yaml
  worker:
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /app/server
    environment:
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      DATABASE_URL: postgresql+asyncpg://trading:trading@db:5432/trading_dashboard
      DASHBOARD_DATA_DIR: /data
      REDIS_URL: redis://redis:6379/0
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY:-}
    volumes:
      - dashdata:/data
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: ["uv", "run", "arq", "app.workers.worker.WorkerSettings"]
```

5. Add the `web` block (unchanged from Wave 1) so the final file order is `db, redis, api, worker, web`.

- [ ] **Step 2: Build and verify**

```bash
cd /Users/erikgunawansupriatna/TradingAgents && docker compose config > /dev/null
```

Expected: valid compose config.

```bash
docker compose build worker
```

Expected: worker image builds (uses the same Dockerfile as `api`).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add redis and arq worker services to docker-compose"
```

---

## Task 18: Extend Playwright E2E with launch + observe

**Files:**
- Modify: `web/tests/e2e/smoke.spec.ts` (keep existing test, add a new one)

This test uses a stub TradingAgentsGraph baked into the worker image via an env var that makes the worker treat the run as a no-op + fixture writer. To keep the plan tractable, the test only verifies the API contract (POST /runs → 202, GET /runs/{id}/tail → polled bytes) — actually executing the full graph in CI requires LLM keys and minutes of runtime.

- [ ] **Step 1: Modify `web/tests/e2e/smoke.spec.ts`** — append a new test:

```typescript
test("launch a run and observe queued status on live monitor", async ({ page }) => {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.goto("/launch");
  await page.getByRole("textbox", { name: /ticker/i }).fill("TSLA");
  await page.getByLabel("Trade date").fill("2024-05-10");
  await page.getByRole("button", { name: /^launch$/i }).click();

  // We should be redirected to /live/<run_id>
  await page.waitForURL(/\/live\/[a-f0-9-]+/);
  await expect(page.getByRole("heading", { name: /TSLA · 2024-05-10/i })).toBeVisible();
  // Status pill renders one of the expected states
  await expect(page.locator("strong").filter({ hasText: /QUEUED|RUNNING|SUCCEEDED|FAILED/ }).first()).toBeVisible();
});
```

- [ ] **Step 2: Verify the test compiles**

```bash
cd web && npx playwright test --list
```

Expected: 2 tests listed.

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/smoke.spec.ts
git commit -m "test(web): e2e launch + observe flow"
```

---

## Task 19: README update + final sanity pass

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append to `README.md`** (after the Wave 1 section)

```markdown

### Wave 2 — Launch + Live Monitor

You can now launch new analyses from the dashboard. The arq worker
runs `TradingAgentsGraph.propagate()` against your namespace; the live
monitor polls `/runs/{id}/tail` every 2s to stream output.

Additional setup:

\`\`\`bash
# Set LLM provider credentials in your .env (read by the worker):
echo "OPENAI_API_KEY=sk-..." >> .env

# The worker service is part of the same docker compose stack:
docker compose up --build
# (web on :3000, api on :8000, worker consuming from redis:6379)
\`\`\`

A run in progress can be watched at \`/live/<run_id>\` and shows the live
\`message_tool.log\` plus a status pill (queued → running → succeeded/failed).
\`\`\`

(escape the triple-backticks like Wave 1's README addition did — the actual file has real fenced code blocks.)

- [ ] **Step 2: Run all tests**

```bash
cd /Users/erikgunawansupriatna/TradingAgents/server && uv run pytest -q
cd /Users/erikgunawansupriatna/TradingAgents/web && NEXTAUTH_SECRET=x AUTH_GITHUB_ID=x AUTH_GITHUB_SECRET=x npm run typecheck
```

Expected: server ~80 passed, frontend zero errors.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document dashboard wave 2 in readme"
```

---

## Wave 2 — Done. What ships:

- **Server**: arq worker + Redis pool + `run_propagate` + `orphan_sweeper` cron + heartbeat loop; `POST /runs` (queue) and `GET /runs/{id}/tail` (polling) endpoints; ~22 new tests.
- **Frontend**: `/launch` page with server action; `/live/[runId]` page with live polling component; tail proxy route; updated nav.
- **Operations**: Unified top-level Dockerfile installs `tradingagents/` root package alongside `server/`. Compose adds `redis` and `worker` services. The api and worker share the same image; same env vars; same Postgres + Redis dependencies.

## Next:

- **Wave 3 plan** will add: memory_mirror service, portfolio_calc (Sharpe / win rate / max DD), `/portfolio` summary endpoint, per-ticker chart with yfinance price overlay, P&L curve component. Spec section: see `docs/superpowers/specs/2026-05-17-trading-dashboard-design.md` section 4 (portfolio_calc) and section 5.3 (portfolio data flow).

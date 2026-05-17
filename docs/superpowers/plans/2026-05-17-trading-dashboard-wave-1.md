# TradingAgents Dashboard — Wave 1 (Skeleton + History) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation of the TradingAgents dashboard — a two-service Docker app (FastAPI + Next.js + Postgres) with GitHub OAuth, per-user filesystem isolation, and read-only browsing of trading-run reports from disk. Lays the groundwork for Wave 2 (Launch + Live monitor) and Wave 3 (Portfolio).

**Architecture:** Monorepo with `server/` (FastAPI, in-process SQLAlchemy async, JWT verification) and `web/` (Next.js App Router, NextAuth GitHub provider, Recharts later). NextAuth mints an HS256 JWT signed with `NEXTAUTH_SECRET`; FastAPI verifies it on every request. Per-user filesystem namespace lives under `${DASHBOARD_DATA_DIR}/users/<user_id>/`. All path joins go through a `user_root` security primitive.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x async, asyncpg / aiosqlite (tests), Alembic, pydantic-settings, PyJWT, pytest-asyncio, httpx · Next.js 15, TypeScript, NextAuth v5, TanStack Query, react-markdown, Playwright · Postgres 16, Docker Compose.

**Reference spec:** `docs/superpowers/specs/2026-05-17-trading-dashboard-design.md`.

---

## File Structure

This wave creates these files; later waves add more.

```
TradingAgents/
├── server/                                  # NEW — FastAPI backend
│   ├── pyproject.toml                       # uv-managed package, deps + ruff
│   ├── .env.example                         # env-var template
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py                           # async migration env
│   │   ├── script.py.mako
│   │   └── versions/                        # generated migration files
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                          # FastAPI() + middleware mount
│   │   ├── config.py                        # pydantic-settings Settings
│   │   ├── db.py                            # async engine + session factory
│   │   ├── auth.py                          # JWT verify + get_current_user dep
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                      # DeclarativeBase
│   │   │   ├── user.py                      # User(id, github_id, email, ...)
│   │   │   └── run.py                       # Run(id, user_id, ticker, ...)
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── user.py                      # UserOut
│   │   │   └── run.py                       # RunOut, RunDetail
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── me.py                        # GET /me
│   │   │   └── runs.py                      # GET /runs, /runs/{id}
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── user_root.py                 # path-join security primitive
│   │   │   └── run_loader.py                # disk → RunDetail loader
│   │   └── scripts/
│   │       ├── __init__.py
│   │       └── import_runs.py               # one-shot CLI: legacy logs → user ns
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py                      # async client, sqlite fixture, JWTs
│   │   ├── test_user_root.py
│   │   ├── test_auth.py
│   │   ├── test_me.py
│   │   ├── test_runs_list.py
│   │   ├── test_runs_detail.py
│   │   └── test_import_runs.py
│   └── Dockerfile
├── web/                                     # NEW — Next.js frontend
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   ├── .env.example
│   ├── app/
│   │   ├── layout.tsx                       # SessionProvider + nav
│   │   ├── page.tsx                         # landing → redirect to /history
│   │   ├── api/auth/[...nextauth]/route.ts  # NextAuth handler
│   │   ├── auth/signin/page.tsx             # styled sign-in
│   │   └── history/
│   │       ├── page.tsx                     # run list
│   │       └── [runId]/page.tsx             # run detail with tabs
│   ├── components/
│   │   ├── Nav.tsx
│   │   ├── RunCard.tsx
│   │   ├── RatingBadge.tsx
│   │   └── ReportTabs.tsx
│   ├── lib/
│   │   ├── auth.ts                          # NextAuth config (GitHub + jwt)
│   │   ├── api.ts                           # typed fetch client → FastAPI
│   │   └── types.ts                         # mirrors server/app/schemas
│   ├── tests/e2e/
│   │   ├── smoke.spec.ts
│   │   └── fixtures/                        # seeded markdown reports
│   ├── playwright.config.ts
│   └── Dockerfile
└── docker-compose.yml                       # NEW: web + api + db
```

**Boundary rules:**
- `web/` NEVER imports from `tradingagents/` or `server/`. Frontend talks to the API over HTTP.
- `server/app/services/user_root.py` is the SINGLE entry point for path joins. Every file read goes through it.
- `tradingagents/` package is untouched in Wave 1.

---

## Conventions

- **TDD**: every task writes the failing test first, runs it, implements, runs again, commits. No exceptions.
- **Commits**: one per task at the end. Format: `<area>(<scope>): <subject>`. Examples: `feat(server): add user_root helper`, `chore(deps): pin fastapi 0.118`.
- **Python deps**: managed in `server/pyproject.toml`, installed with `uv`. Run commands assume `cd server` unless noted.
- **TS deps**: managed in `web/package.json`, installed with `npm` (Next.js's default). Run commands assume `cd web`.
- **Run all server tests**: `cd server && uv run pytest -q`. Run a single test: `uv run pytest tests/test_foo.py::test_bar -v`.
- **Lint**: `cd server && uv run ruff check . && uv run ruff format --check .`

---

## Task 1: Scaffold the `server/` package

**Files:**
- Create: `server/pyproject.toml`
- Create: `server/.env.example`
- Create: `server/app/__init__.py` (empty)
- Create: `server/app/main.py`
- Create: `server/tests/__init__.py` (empty)
- Create: `server/tests/conftest.py`
- Create: `server/tests/test_health.py`

- [ ] **Step 1: Create `server/pyproject.toml`**

```toml
[project]
name = "tradingagents-server"
version = "0.1.0"
description = "FastAPI backend for the TradingAgents dashboard"
requires-python = ">=3.10"
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
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "anyio>=4.6",
    "ruff>=0.7",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S"]
ignore = ["S101"]  # allow asserts in tests
```

- [ ] **Step 2: Create `server/.env.example`**

```bash
# Shared with web/ (NextAuth) — MUST match
NEXTAUTH_SECRET=replace-me-with-32-bytes-of-base64

# Database
DATABASE_URL=postgresql+asyncpg://trading:trading@localhost:5432/trading_dashboard
# For tests, conftest.py overrides to sqlite+aiosqlite:///:memory:

# Per-user filesystem root
DASHBOARD_DATA_DIR=/var/lib/trading/dashboard

# Legacy importer source (existing CLI logs)
LEGACY_RESULTS_DIR=
```

- [ ] **Step 3: Write the failing health-check test**

Create `server/tests/test_health.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_healthz_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

Create `server/tests/conftest.py` (skeleton — extended later tasks add fixtures):

```python
import os

os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-do-not-use-in-prod-xxxxxxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DASHBOARD_DATA_DIR", "/tmp/trading-test")
```

- [ ] **Step 4: Run it; expect failure**

```bash
cd server && uv sync && uv run pytest tests/test_health.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 5: Create the minimal app**

Create `server/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="TradingAgents Dashboard API")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Run it; expect pass**

```bash
cd server && uv run pytest tests/test_health.py -v
```

Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add server/ docs/superpowers/plans/2026-05-17-trading-dashboard-wave-1.md
git commit -m "feat(server): scaffold fastapi server with health endpoint"
```

---

## Task 2: Settings via pydantic-settings

**Files:**
- Create: `server/app/config.py`
- Create: `server/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_config.py`:

```python
import os

from app.config import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    s = Settings()
    assert s.nextauth_secret == "abc"
    assert s.database_url.startswith("sqlite+aiosqlite")
    assert str(s.dashboard_data_dir) == "/tmp/x"


def test_settings_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DASHBOARD_DATA_DIR", "/tmp/x")
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings()
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_config.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `server/app/config.py`**

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nextauth_secret: str = Field(min_length=16)
    database_url: str
    dashboard_data_dir: Path
    legacy_results_dir: Path | None = None
    jwt_algorithm: str = "HS256"
    jwt_audience: str | None = None
    max_tail_bytes: int = 64 * 1024

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/config.py server/tests/test_config.py
git commit -m "feat(server): add pydantic-settings config layer"
```

---

## Task 3: `user_root` security primitive

This is **load-bearing for security**. Every filesystem access in the server flows through it. Test it adversarially.

**Files:**
- Create: `server/app/services/__init__.py` (empty)
- Create: `server/app/services/user_root.py`
- Create: `server/tests/test_user_root.py`

- [ ] **Step 1: Write the failing adversarial tests**

Create `server/tests/test_user_root.py`:

```python
import uuid
from pathlib import Path

import pytest

from app.services.user_root import (
    InvalidUserIdError,
    PathEscapeError,
    user_results_dir,
    user_run_dir,
)

GOOD = str(uuid.uuid4())
BAD_IDS = [
    "../etc",
    "..",
    "",
    "/abs/path",
    "f0" * 17 + "g0",  # right length, invalid hex
    "not-a-uuid",
    "f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0\0",  # nul byte
    " " + str(uuid.uuid4()),
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "dash"


def test_user_results_dir_creates_under_user_namespace(root: Path):
    p = user_results_dir(root, GOOD)
    assert p == root / "users" / GOOD
    assert root in p.parents


def test_user_run_dir_joins_ticker_and_date(root: Path):
    p = user_run_dir(root, GOOD, "NVDA", "2024-05-10")
    assert p == root / "users" / GOOD / "NVDA" / "2024-05-10"


@pytest.mark.parametrize("bad", BAD_IDS)
def test_invalid_user_id_rejected(root: Path, bad: str):
    with pytest.raises(InvalidUserIdError):
        user_results_dir(root, bad)


@pytest.mark.parametrize(
    "ticker",
    ["..", "../etc", "/abs", "NVDA/../AAPL", "NV\0DA", "", " NVDA"],
)
def test_path_escape_in_ticker_rejected(root: Path, ticker: str):
    with pytest.raises(PathEscapeError):
        user_run_dir(root, GOOD, ticker, "2024-05-10")


@pytest.mark.parametrize(
    "date",
    ["..", "2024/05/10", "2024-05-10/../..", "2024-05-10\0", "", "2024-05-1"],
)
def test_path_escape_in_date_rejected(root: Path, date: str):
    with pytest.raises(PathEscapeError):
        user_run_dir(root, GOOD, "NVDA", date)


def test_resolved_path_must_be_inside_root(root: Path):
    # Even if all components individually look safe, the resolved path must
    # remain inside root. Symlink-escape style attacks would surface here.
    root.mkdir(parents=True)
    (root / "users").mkdir()
    (root / "users" / GOOD).mkdir()
    p = user_run_dir(root, GOOD, "NVDA", "2024-05-10")
    p.mkdir(parents=True)
    assert root.resolve() in p.resolve().parents
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_user_root.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `server/app/services/user_root.py`**

```python
"""Per-user path-join security primitive.

Every filesystem access in the dashboard server MUST go through one of the
functions here. This module is the single trust boundary for path
construction. Treat it as security-critical.
"""

from __future__ import annotations

import re
from pathlib import Path

USER_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidUserIdError(ValueError):
    """Raised when a user_id doesn't match the expected UUID format."""


class PathEscapeError(ValueError):
    """Raised when a path component would escape the user namespace."""


def _check_user_id(user_id: str) -> None:
    if not isinstance(user_id, str) or not USER_ID_RE.fullmatch(user_id):
        raise InvalidUserIdError(f"invalid user_id: {user_id!r}")


def _check_segment(name: str, value: str, pattern: re.Pattern[str]) -> None:
    if not isinstance(value, str) or "\0" in value or not pattern.fullmatch(value):
        raise PathEscapeError(f"invalid {name}: {value!r}")


def user_results_dir(root: Path, user_id: str) -> Path:
    """Return the user's namespace root: <root>/users/<user_id>."""
    _check_user_id(user_id)
    return Path(root) / "users" / user_id


def user_run_dir(root: Path, user_id: str, ticker: str, trade_date: str) -> Path:
    """Return the directory holding a specific run's artifacts."""
    _check_user_id(user_id)
    _check_segment("ticker", ticker, TICKER_RE)
    _check_segment("trade_date", trade_date, DATE_RE)
    return user_results_dir(root, user_id) / ticker / trade_date


def user_report_file(
    root: Path, user_id: str, ticker: str, trade_date: str, filename: str
) -> Path:
    """Return the path to a specific report markdown file under reports/."""
    if not isinstance(filename, str) or "/" in filename or "\\" in filename or "\0" in filename:
        raise PathEscapeError(f"invalid filename: {filename!r}")
    if not filename.endswith(".md"):
        raise PathEscapeError(f"only .md filenames allowed: {filename!r}")
    return user_run_dir(root, user_id, ticker, trade_date) / "reports" / filename
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_user_root.py -v
```

Expected: all parametrized cases pass (≈20 cases).

- [ ] **Step 5: Commit**

```bash
git add server/app/services/ server/tests/test_user_root.py
git commit -m "feat(server): add user_root path-join security primitive"
```

---

## Task 4: Async DB engine + DeclarativeBase

**Files:**
- Create: `server/app/db.py`
- Create: `server/app/models/__init__.py`
- Create: `server/app/models/base.py`
- Create: `server/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_db.py`:

```python
import pytest
from sqlalchemy import text

from app.db import get_engine, get_session_factory


@pytest.mark.asyncio
async def test_engine_round_trip():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_session_factory_yields_async_session():
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(text("SELECT 2"))
        assert result.scalar() == 2
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_db.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `server/app/models/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
```

Create `server/app/models/__init__.py`:

```python
from app.models.base import Base

__all__ = ["Base"]
```

Implement `server/app/db.py`:

```python
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, future=True, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:
    """FastAPI dependency yielding an async session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_db.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/db.py server/app/models/
git commit -m "feat(server): add async sqlalchemy engine and session factory"
```

---

## Task 5: User and Run ORM models + table creation fixture

**Files:**
- Create: `server/app/models/user.py`
- Create: `server/app/models/run.py`
- Modify: `server/tests/conftest.py` (add fixtures)
- Create: `server/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_models.py`:

```python
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.run import Run, RunStatus
from app.models.user import User


@pytest.mark.asyncio
async def test_user_insert_and_query(db_session):
    u = User(id=uuid.uuid4(), github_id="123", email="a@example.com")
    db_session.add(u)
    await db_session.flush()
    rows = (await db_session.execute(select(User))).scalars().all()
    assert len(rows) == 1
    assert rows[0].github_id == "123"


@pytest.mark.asyncio
async def test_run_insert_and_query(db_session):
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, github_id="42", email="b@example.com"))
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker="NVDA",
        trade_date="2024-05-10",
        status=RunStatus.SUCCEEDED,
        results_path="users/" + str(user_id) + "/NVDA/2024-05-10",
        final_rating="Buy",
        created_at=datetime.utcnow(),
    )
    db_session.add(run)
    await db_session.flush()
    found = (await db_session.execute(select(Run))).scalar_one()
    assert found.ticker == "NVDA"
    assert found.status is RunStatus.SUCCEEDED
```

Modify `server/tests/conftest.py` to add the fixture (replace the file):

```python
import os
import uuid

os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-do-not-use-in-prod-xxxxxxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DASHBOARD_DATA_DIR", "/tmp/trading-test")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
# Import models so their tables are registered on Base.metadata
from app.models import user as _user  # noqa: F401
from app.models import run as _run  # noqa: F401


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_models.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `server/app/models/user.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    github_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Implement `server/app/models/run.py`:

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), index=True
    )
    final_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    results_path: Mapped[str] = mapped_column(String(1024))
    error_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(nullable=True)  # TEXT
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_models.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/models/ server/tests/conftest.py server/tests/test_models.py
git commit -m "feat(server): add user and run orm models"
```

---

## Task 6: Alembic baseline migration

**Files:**
- Create: `server/alembic.ini`
- Create: `server/alembic/env.py`
- Create: `server/alembic/script.py.mako`
- Create: `server/alembic/versions/<auto>_initial.py` (generated)
- Create: `server/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_migrations.py`:

```python
import subprocess
from pathlib import Path


def test_alembic_upgrade_head(tmp_path: Path):
    """`alembic upgrade head` against a fresh sqlite db must succeed."""
    db_file = tmp_path / "mig.db"
    env = {
        "PATH": _path_env(),
        "NEXTAUTH_SECRET": "test-secret-do-not-use-in-prod-xxxxxxxx",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}",
        "DASHBOARD_DATA_DIR": str(tmp_path),
    }
    server_dir = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=server_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert db_file.exists()


def _path_env() -> str:
    import os

    return os.environ["PATH"]
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_migrations.py -v
```

Expected: `alembic: command not found` or "no such config file".

- [ ] **Step 3: Initialize Alembic**

```bash
cd server && uv run alembic init alembic
```

Edit `server/alembic.ini` and change the `sqlalchemy.url` line to:

```ini
sqlalchemy.url =
```

Replace `server/alembic/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import get_settings
from app.models.base import Base
from app.models import user as _user  # noqa: F401
from app.models import run as _run  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()
```

Generate the first migration:

```bash
cd server && uv run alembic revision --autogenerate -m "initial schema"
```

This creates a file like `server/alembic/versions/abc123_initial_schema.py`. Inspect it; it should contain `users` and `runs` table definitions.

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_migrations.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add server/alembic.ini server/alembic/ server/tests/test_migrations.py
git commit -m "feat(server): add alembic baseline migration"
```

---

## Task 7: JWT verification + `get_current_user` dependency

**Files:**
- Create: `server/app/auth.py`
- Modify: `server/tests/conftest.py` (add JWT-minting helper)
- Create: `server/tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/conftest.py`:

```python
import datetime as _dt
import time

import jwt


def make_jwt(github_id: str, email: str | None = "a@example.com", *, exp_in: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": github_id, "email": email, "iat": now, "exp": now + exp_in},
        os.environ["NEXTAUTH_SECRET"],
        algorithm="HS256",
    )


def make_expired_jwt(github_id: str) -> str:
    return make_jwt(github_id, exp_in=-10)
```

Create `server/tests/test_auth.py`:

```python
import uuid

import pytest
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import get_current_user
from app.models.user import User
from tests.conftest import make_expired_jwt, make_jwt


@pytest.fixture
def auth_app(db_session):
    app = FastAPI()

    async def _override_db():
        yield db_session

    from app.db import get_db
    app.dependency_overrides[get_db] = _override_db

    @app.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)):
        return {"id": str(user.id), "github_id": user.github_id}

    return app


async def _call(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/whoami", headers=headers)


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(auth_app):
    r = await _call(auth_app, {})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_jwt_upserts_user(auth_app, db_session):
    token = make_jwt("gh-100")
    r = await _call(auth_app, {"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["github_id"] == "gh-100"
    rows = (await db_session.execute(select(User))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_repeat_login_does_not_duplicate_user(auth_app, db_session):
    token = make_jwt("gh-200")
    await _call(auth_app, {"Authorization": f"Bearer {token}"})
    await _call(auth_app, {"Authorization": f"Bearer {token}"})
    rows = (await db_session.execute(select(User))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(auth_app):
    r = await _call(auth_app, {"Authorization": f"Bearer {make_expired_jwt('gh-300')}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bad_signature_returns_401(auth_app):
    token = make_jwt("gh-400")
    tampered = token[:-4] + "xxxx"
    r = await _call(auth_app, {"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_auth.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `server/app/auth.py`**

```python
import uuid

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.user import User


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )
    return authorization.split(None, 1)[1]


def _decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.nextauth_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            options={"verify_aud": settings.jwt_audience is not None},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = _decode_token(_extract_token(authorization))
    github_id = payload.get("sub")
    if not github_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )
    email = payload.get("email")
    user = (
        await db.execute(select(User).where(User.github_id == github_id))
    ).scalar_one_or_none()
    if user is None:
        user = User(id=uuid.uuid4(), github_id=github_id, email=email)
        db.add(user)
        await db.flush()
    return user
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_auth.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/auth.py server/tests/test_auth.py server/tests/conftest.py
git commit -m "feat(server): add jwt verification and get_current_user dep"
```

---

## Task 8: `GET /me` endpoint and schema

**Files:**
- Create: `server/app/schemas/__init__.py` (empty)
- Create: `server/app/schemas/user.py`
- Create: `server/app/routers/__init__.py` (empty)
- Create: `server/app/routers/me.py`
- Modify: `server/app/main.py`
- Create: `server/tests/test_me.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_me.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from tests.conftest import make_jwt


@pytest.fixture
def client(db_session):
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_me_returns_user_payload(client):
    token = make_jwt("gh-77", email="x@example.com")
    async with client as c:
        r = await c.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["github_id"] == "gh-77"
    assert body["email"] == "x@example.com"
    assert "id" in body and "created_at" in body
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_me.py -v
```

Expected: 404.

- [ ] **Step 3: Implement**

Create `server/app/schemas/user.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    id: uuid.UUID
    github_id: str
    email: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

Create `server/app/routers/me.py`:

```python
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserOut

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
```

Update `server/app/main.py`:

```python
from fastapi import FastAPI

from app.routers import me as me_router

app = FastAPI(title="TradingAgents Dashboard API")
app.include_router(me_router.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_me.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/schemas/ server/app/routers/ server/app/main.py server/tests/test_me.py
git commit -m "feat(server): add /me endpoint"
```

---

## Task 9: Run-list endpoint `GET /runs`

**Files:**
- Create: `server/app/schemas/run.py`
- Create: `server/app/routers/runs.py`
- Modify: `server/app/main.py`
- Create: `server/tests/test_runs_list.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_runs_list.py`:

```python
import uuid
from datetime import datetime

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


def _add_run(session, *, user_id, ticker, date, status=RunStatus.SUCCEEDED, rating="Buy"):
    r = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        ticker=ticker,
        trade_date=date,
        status=status,
        final_rating=rating,
        results_path=f"users/{user_id}/{ticker}/{date}",
        created_at=datetime.utcnow(),
    )
    session.add(r)
    return r


@pytest.mark.asyncio
async def test_runs_list_filters_by_authenticated_user(client, db_session):
    me_id, other_id = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me_id, github_id="gh-me"))
    db_session.add(User(id=other_id, github_id="gh-other"))
    _add_run(db_session, user_id=me_id, ticker="NVDA", date="2024-05-10")
    _add_run(db_session, user_id=me_id, ticker="AAPL", date="2024-05-09")
    _add_run(db_session, user_id=other_id, ticker="TSLA", date="2024-05-08")
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/runs",
            headers={"Authorization": f"Bearer {make_jwt('gh-me')}"},
        )
    assert r.status_code == 200
    items = r.json()["items"]
    assert {it["ticker"] for it in items} == {"NVDA", "AAPL"}
    # newest first
    assert items[0]["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_runs_list_supports_ticker_filter(client, db_session):
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-f"))
    _add_run(db_session, user_id=uid, ticker="NVDA", date="2024-05-10")
    _add_run(db_session, user_id=uid, ticker="AAPL", date="2024-05-09")
    await db_session.flush()

    async with client as c:
        r = await c.get(
            "/runs?ticker=NVDA",
            headers={"Authorization": f"Bearer {make_jwt('gh-f')}"},
        )
    assert r.status_code == 200
    items = r.json()["items"]
    assert {it["ticker"] for it in items} == {"NVDA"}


@pytest.mark.asyncio
async def test_runs_list_requires_auth(client):
    async with client as c:
        r = await c.get("/runs")
    assert r.status_code == 401
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_runs_list.py -v
```

Expected: 404 / `ImportError`.

- [ ] **Step 3: Implement**

Create `server/app/schemas/run.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RunOut(BaseModel):
    id: uuid.UUID
    ticker: str
    trade_date: str
    status: str
    final_rating: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RunListOut(BaseModel):
    items: list[RunOut]


class ReportSections(BaseModel):
    market: str | None = None
    sentiment: str | None = None
    news: str | None = None
    fundamentals: str | None = None
    investment_plan: str | None = None
    trader_plan: str | None = None
    final: str | None = None


class RunDetailOut(RunOut):
    results_path: str
    error_summary: str | None
    report_sections: ReportSections
```

Create `server/app/routers/runs.py`:

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.run import Run
from app.models.user import User
from app.schemas.run import RunListOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunListOut)
async def list_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    ticker: str | None = Query(default=None, max_length=12),
    limit: int = Query(default=50, ge=1, le=200),
) -> RunListOut:
    stmt = (
        select(Run)
        .where(Run.user_id == user.id)
        .order_by(Run.trade_date.desc(), Run.created_at.desc())
        .limit(limit)
    )
    if ticker:
        stmt = stmt.where(Run.ticker == ticker.upper())
    rows = (await db.execute(stmt)).scalars().all()
    return RunListOut(items=[RunOut.model_validate(r) for r in rows])
```

Update `server/app/main.py`:

```python
from fastapi import FastAPI

from app.routers import me as me_router
from app.routers import runs as runs_router

app = FastAPI(title="TradingAgents Dashboard API")
app.include_router(me_router.router)
app.include_router(runs_router.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_runs_list.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/schemas/run.py server/app/routers/runs.py server/app/main.py server/tests/test_runs_list.py
git commit -m "feat(server): add /runs list endpoint with per-user filter"
```

---

## Task 10: Run-detail endpoint `GET /runs/{id}` (reads markdown from disk)

**Files:**
- Create: `server/app/services/run_loader.py`
- Modify: `server/app/routers/runs.py`
- Create: `server/tests/test_runs_detail.py`

The endpoint joins the DB Run row with the markdown files on disk. The mapping from logical section name → on-disk filename matches what `cli/main.py:save_report_to_disk()` already writes today:

| Section | Path under `<run_dir>/reports/` |
|---|---|
| `market` | `1_analysts/market.md` |
| `sentiment` | `1_analysts/sentiment.md` |
| `news` | `1_analysts/news.md` |
| `fundamentals` | `1_analysts/fundamentals.md` |
| `investment_plan` | `2_research/manager.md` |
| `trader_plan` | `3_trading/trader.md` |
| `final` | `final_trade_decision.md` |

Bull/bear/risk-judge sections come in Wave 2's view; v1 surfaces the 7 above.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_runs_detail.py`:

```python
import uuid
from datetime import datetime
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


def _seed_run_on_disk(root: Path, user_id, ticker, date) -> Path:
    base = root / "users" / str(user_id) / ticker / date / "reports"
    (base / "1_analysts").mkdir(parents=True)
    (base / "2_research").mkdir(parents=True)
    (base / "3_trading").mkdir(parents=True)
    (base / "1_analysts" / "market.md").write_text("# market report")
    (base / "2_research" / "manager.md").write_text("# research mgr")
    (base / "3_trading" / "trader.md").write_text("# trader plan")
    (base / "final_trade_decision.md").write_text("# final")
    return base.parent.parent.parent.parent


@pytest.mark.asyncio
async def test_run_detail_returns_markdown_sections(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-d"))
    _seed_run_on_disk(tmp_path, uid, "NVDA", "2024-05-10")
    run_id = uuid.uuid4()
    db_session.add(
        Run(
            id=run_id,
            user_id=uid,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED,
            final_rating="Buy",
            results_path=str(tmp_path / "users" / str(uid) / "NVDA" / "2024-05-10"),
            created_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{run_id}",
            headers={"Authorization": f"Bearer {make_jwt('gh-d')}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["report_sections"]["market"].startswith("# market")
    assert body["report_sections"]["final"].startswith("# final")
    assert body["report_sections"]["sentiment"] is None


@pytest.mark.asyncio
async def test_run_detail_404_for_other_users_run(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    me, other = uuid.uuid4(), uuid.uuid4()
    db_session.add(User(id=me, github_id="gh-me"))
    db_session.add(User(id=other, github_id="gh-other"))
    other_run = uuid.uuid4()
    db_session.add(
        Run(
            id=other_run,
            user_id=other,
            ticker="NVDA",
            trade_date="2024-05-10",
            status=RunStatus.SUCCEEDED,
            results_path="x",
            created_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    async with client as c:
        r = await c.get(
            f"/runs/{other_run}",
            headers={"Authorization": f"Bearer {make_jwt('gh-me')}"},
        )
    # 404, NOT 403 — avoid existence oracle.
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_run_detail_422_for_non_uuid(client):
    async with client as c:
        r = await c.get(
            "/runs/not-a-uuid",
            headers={"Authorization": f"Bearer {make_jwt('gh-x')}"},
        )
    assert r.status_code == 422
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_runs_detail.py -v
```

Expected: 404 / `ImportError`.

- [ ] **Step 3: Implement `server/app/services/run_loader.py`**

```python
from __future__ import annotations

from pathlib import Path

from app.schemas.run import ReportSections

# section name → relative path under <results_path>/reports/
_SECTION_FILES: dict[str, tuple[str, ...]] = {
    "market": ("1_analysts", "market.md"),
    "sentiment": ("1_analysts", "sentiment.md"),
    "news": ("1_analysts", "news.md"),
    "fundamentals": ("1_analysts", "fundamentals.md"),
    "investment_plan": ("2_research", "manager.md"),
    "trader_plan": ("3_trading", "trader.md"),
    "final": ("final_trade_decision.md",),
}


def load_report_sections(results_path: str) -> ReportSections:
    """Read all known markdown sections from a run's results_path.

    Missing files are returned as None. Paths are joined under the supplied
    results_path; the caller is responsible for ensuring results_path was
    produced by `user_root` (this function does not re-validate).
    """
    base = Path(results_path) / "reports"
    out: dict[str, str | None] = {}
    for section, parts in _SECTION_FILES.items():
        path = base.joinpath(*parts)
        if path.is_file():
            try:
                out[section] = path.read_text(encoding="utf-8")
            except OSError:
                out[section] = None
        else:
            out[section] = None
    return ReportSections(**out)
```

Append to `server/app/routers/runs.py`:

```python
import uuid as _uuid

from fastapi import HTTPException, status

from app.schemas.run import RunDetailOut
from app.services.run_loader import load_report_sections


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: _uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunDetailOut:
    run = (
        await db.execute(
            select(Run).where(Run.id == run_id, Run.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    sections = load_report_sections(run.results_path)
    return RunDetailOut.model_validate(
        {**run.__dict__, "report_sections": sections.model_dump()}
    )
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_runs_detail.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/run_loader.py server/app/routers/runs.py server/tests/test_runs_detail.py
git commit -m "feat(server): add /runs/{id} detail with markdown sections"
```

---

## Task 11: One-shot importer for legacy CLI runs

Walks `LEGACY_RESULTS_DIR` (e.g. `~/.tradingagents/logs`), copies each `<TICKER>/<DATE>/` tree into the per-user namespace, and inserts `Run` rows. Idempotent: re-running with the same target user does nothing for already-imported runs.

**Files:**
- Create: `server/app/scripts/__init__.py` (empty)
- Create: `server/app/scripts/import_runs.py`
- Create: `server/tests/test_import_runs.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_import_runs.py`:

```python
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.run import Run
from app.models.user import User
from app.scripts.import_runs import import_legacy_runs


def _seed_legacy(root: Path, ticker: str, date: str) -> None:
    base = root / ticker / date / "reports" / "1_analysts"
    base.mkdir(parents=True)
    (base / "market.md").write_text("legacy market")
    (root / ticker / date / "final_trade_decision.md").write_text("legacy final")


@pytest.mark.asyncio
async def test_import_copies_files_and_creates_run_rows(db_session, tmp_path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "dash"
    _seed_legacy(legacy, "NVDA", "2024-05-10")
    _seed_legacy(legacy, "AAPL", "2024-05-09")

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-import"))
    await db_session.flush()

    n = await import_legacy_runs(
        session=db_session,
        legacy_dir=legacy,
        dashboard_dir=target,
        user_id=uid,
    )
    assert n == 2
    rows = (await db_session.execute(select(Run))).scalars().all()
    assert {r.ticker for r in rows} == {"NVDA", "AAPL"}
    assert (target / "users" / str(uid) / "NVDA" / "2024-05-10" / "reports" /
            "1_analysts" / "market.md").read_text() == "legacy market"


@pytest.mark.asyncio
async def test_import_is_idempotent(db_session, tmp_path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "dash"
    _seed_legacy(legacy, "NVDA", "2024-05-10")
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-id2"))
    await db_session.flush()

    n1 = await import_legacy_runs(session=db_session, legacy_dir=legacy,
                                  dashboard_dir=target, user_id=uid)
    n2 = await import_legacy_runs(session=db_session, legacy_dir=legacy,
                                  dashboard_dir=target, user_id=uid)
    assert n1 == 1 and n2 == 0
    rows = (await db_session.execute(select(Run))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_import_rejects_bad_ticker_or_date_segments(db_session, tmp_path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "dash"
    (legacy / ".." / "weird").mkdir(parents=True, exist_ok=True)
    (legacy / "lowercase" / "2024-05-10").mkdir(parents=True)
    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-id3"))
    await db_session.flush()
    # Should silently skip non-conforming dirs, not raise.
    n = await import_legacy_runs(session=db_session, legacy_dir=legacy,
                                 dashboard_dir=target, user_id=uid)
    assert n == 0
```

- [ ] **Step 2: Run; expect failure**

```bash
cd server && uv run pytest tests/test_import_runs.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `server/app/scripts/import_runs.py`**

```python
"""One-shot CLI: import legacy ``~/.tradingagents/logs`` runs into a
per-user dashboard namespace.

Usage:
    uv run python -m app.scripts.import_runs \
        --github-id <gh-username> \
        --legacy-dir ~/.tradingagents/logs \
        --dashboard-dir /var/lib/trading/dashboard
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models.run import Run, RunStatus
from app.models.user import User
from app.services.user_root import (
    DATE_RE,
    TICKER_RE,
    user_run_dir,
)


async def import_legacy_runs(
    *,
    session: AsyncSession,
    legacy_dir: Path,
    dashboard_dir: Path,
    user_id: uuid.UUID,
) -> int:
    """Copy each <ticker>/<date>/ subtree into the user namespace.

    Returns the number of NEW Run rows inserted (skips already-imported).
    """
    legacy_dir = Path(legacy_dir)
    dashboard_dir = Path(dashboard_dir)
    if not legacy_dir.is_dir():
        return 0

    inserted = 0
    for ticker_dir in legacy_dir.iterdir():
        if not ticker_dir.is_dir():
            continue
        ticker = ticker_dir.name
        if not TICKER_RE.fullmatch(ticker):
            continue
        for date_dir in ticker_dir.iterdir():
            if not date_dir.is_dir():
                continue
            date = date_dir.name
            if not DATE_RE.fullmatch(date):
                continue
            target = user_run_dir(dashboard_dir, str(user_id), ticker, date)
            existing = (
                await session.execute(
                    select(Run).where(
                        Run.user_id == user_id,
                        Run.ticker == ticker,
                        Run.trade_date == date,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            target.mkdir(parents=True, exist_ok=True)
            for child in date_dir.iterdir():
                dst = target / child.name
                if child.is_dir():
                    shutil.copytree(child, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, dst)
            session.add(
                Run(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    ticker=ticker,
                    trade_date=date,
                    status=RunStatus.SUCCEEDED,
                    results_path=str(target),
                    final_rating=_extract_final_rating(target),
                    created_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
            )
            inserted += 1
    await session.flush()
    return inserted


def _extract_final_rating(run_dir: Path) -> str | None:
    final = run_dir / "final_trade_decision.md"
    if not final.is_file():
        return None
    text = final.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        if "**Rating**:" in line:
            return line.split("**Rating**:", 1)[1].strip().strip("*").split()[0]
    return None


async def _async_main(github_id: str, legacy_dir: Path, dashboard_dir: Path) -> None:
    factory = get_session_factory()
    async with factory() as session:
        user = (
            await session.execute(select(User).where(User.github_id == github_id))
        ).scalar_one_or_none()
        if user is None:
            user = User(id=uuid.uuid4(), github_id=github_id)
            session.add(user)
            await session.flush()
        n = await import_legacy_runs(
            session=session,
            legacy_dir=legacy_dir,
            dashboard_dir=dashboard_dir,
            user_id=user.id,
        )
        await session.commit()
        print(f"imported {n} runs for user_id={user.id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-id", required=True)
    parser.add_argument("--legacy-dir", required=True, type=Path)
    parser.add_argument("--dashboard-dir", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_async_main(args.github_id, args.legacy_dir, args.dashboard_dir))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run; expect pass**

```bash
cd server && uv run pytest tests/test_import_runs.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add server/app/scripts/ server/tests/test_import_runs.py
git commit -m "feat(server): add legacy run importer script"
```

---

## Task 12: Scaffold the `web/` Next.js app

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/next.config.js`
- Create: `web/.env.example`
- Create: `web/app/layout.tsx`
- Create: `web/app/page.tsx`

- [ ] **Step 1: Write `web/package.json`**

```json
{
  "name": "tradingagents-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "next-auth": "^5.0.0-beta.25",
    "@tanstack/react-query": "^5.59.0",
    "react-markdown": "^9.0.0",
    "remark-gfm": "^4.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.6.0"
  }
}
```

- [ ] **Step 2: Write `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "es2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./*"] },
    "plugins": [{ "name": "next" }]
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Write `web/next.config.js`**

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};
module.exports = nextConfig;
```

- [ ] **Step 4: Write `web/.env.example`**

```bash
# MUST match server/.env NEXTAUTH_SECRET
NEXTAUTH_SECRET=replace-me-with-32-bytes-of-base64
NEXTAUTH_URL=http://localhost:3000

# GitHub OAuth (https://github.com/settings/developers — set callback
# to ${NEXTAUTH_URL}/api/auth/callback/github)
AUTH_GITHUB_ID=
AUTH_GITHUB_SECRET=

# Where the FastAPI service lives
API_BASE_URL=http://localhost:8000
```

- [ ] **Step 5: Minimal placeholder pages**

Create `web/app/layout.tsx`:

```tsx
import type { ReactNode } from "react";

export const metadata = { title: "TradingAgents Dashboard" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>
        {children}
      </body>
    </html>
  );
}
```

Create `web/app/page.tsx`:

```tsx
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/history");
}
```

- [ ] **Step 6: Verify the build works**

```bash
cd web && npm install && npm run typecheck && npm run build
```

Expected: build succeeds (the `redirect()` triggers a build-time warning about needing dynamic; this is fine).

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/tsconfig.json web/next.config.js web/.env.example web/app/
git commit -m "feat(web): scaffold next.js app router skeleton"
```

---

## Task 13: NextAuth GitHub provider + JWT signing

**Files:**
- Create: `web/lib/auth.ts`
- Create: `web/app/api/auth/[...nextauth]/route.ts`
- Modify: `web/app/layout.tsx`
- Create: `web/components/SessionProviderClient.tsx`

- [ ] **Step 1: Implement NextAuth config**

Create `web/lib/auth.ts`:

```ts
import NextAuth, { type NextAuthConfig } from "next-auth";
import GitHub from "next-auth/providers/github";

const secret = process.env.NEXTAUTH_SECRET;
if (!secret) throw new Error("NEXTAUTH_SECRET is required");

export const authConfig: NextAuthConfig = {
  providers: [
    GitHub({
      clientId: process.env.AUTH_GITHUB_ID!,
      clientSecret: process.env.AUTH_GITHUB_SECRET!,
    }),
  ],
  session: { strategy: "jwt" },
  jwt: {
    // HS256 by default — matches server/app/auth.py
  },
  callbacks: {
    async jwt({ token, profile }) {
      // GitHub profile.id is the numeric user id (number); coerce to string
      if (profile && (profile as { id?: number | string }).id !== undefined) {
        token.sub = String((profile as { id: number | string }).id);
      }
      if (profile && (profile as { email?: string }).email) {
        token.email = (profile as { email: string }).email;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) (session.user as { githubId?: string }).githubId = token.sub;
      return session;
    },
  },
  secret,
};

export const { handlers, signIn, signOut, auth } = NextAuth(authConfig);
```

Create `web/app/api/auth/[...nextauth]/route.ts`:

```ts
import { handlers } from "@/lib/auth";

export const { GET, POST } = handlers;
```

- [ ] **Step 2: Add a client-side SessionProvider wrapper**

Create `web/components/SessionProviderClient.tsx`:

```tsx
"use client";
import { SessionProvider } from "next-auth/react";
import type { ReactNode } from "react";

export default function SessionProviderClient({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
```

Replace `web/app/layout.tsx`:

```tsx
import type { ReactNode } from "react";
import SessionProviderClient from "@/components/SessionProviderClient";

export const metadata = { title: "TradingAgents Dashboard" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>
        <SessionProviderClient>{children}</SessionProviderClient>
      </body>
    </html>
  );
}
```

- [ ] **Step 3: Verify build still passes**

```bash
cd web && npm run typecheck && npm run build
```

Expected: clean build (warnings about missing `AUTH_GITHUB_ID` are fine — those are runtime concerns).

- [ ] **Step 4: Commit**

```bash
git add web/lib/auth.ts web/app/api/ web/app/layout.tsx web/components/SessionProviderClient.tsx
git commit -m "feat(web): wire nextauth github provider with shared-secret jwt"
```

---

## Task 14: Typed API client with JWT injection

**Files:**
- Create: `web/lib/types.ts`
- Create: `web/lib/api.ts`

- [ ] **Step 1: Define shared types**

Create `web/lib/types.ts`:

```ts
export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface RunOut {
  id: string;
  ticker: string;
  trade_date: string;
  status: RunStatus;
  final_rating: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface RunListOut {
  items: RunOut[];
}

export interface ReportSections {
  market: string | null;
  sentiment: string | null;
  news: string | null;
  fundamentals: string | null;
  investment_plan: string | null;
  trader_plan: string | null;
  final: string | null;
}

export interface RunDetailOut extends RunOut {
  results_path: string;
  error_summary: string | null;
  report_sections: ReportSections;
}

export interface UserOut {
  id: string;
  github_id: string;
  email: string | null;
  created_at: string;
}
```

- [ ] **Step 2: Implement the fetch client**

Create `web/lib/api.ts`:

```ts
import { auth } from "@/lib/auth";
import { encode } from "next-auth/jwt";
import type { RunDetailOut, RunListOut, UserOut } from "@/lib/types";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

async function bearer(): Promise<string> {
  const session = await auth();
  if (!session?.user) throw new Error("unauthenticated");
  // Re-encode the JWT so FastAPI receives the same HS256-signed token.
  const token = await encode({
    token: {
      sub: (session.user as { githubId?: string }).githubId,
      email: session.user.email ?? null,
    },
    secret: process.env.NEXTAUTH_SECRET!,
    salt: "",
  });
  return `Bearer ${token}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: await bearer() },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`api ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => get<UserOut>("/me"),
  listRuns: (ticker?: string) =>
    get<RunListOut>(ticker ? `/runs?ticker=${encodeURIComponent(ticker)}` : "/runs"),
  getRun: (id: string) => get<RunDetailOut>(`/runs/${id}`),
};
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add web/lib/types.ts web/lib/api.ts
git commit -m "feat(web): add typed fastapi client with jwt injection"
```

---

## Task 15: `/history` list page

**Files:**
- Create: `web/components/Nav.tsx`
- Create: `web/components/RatingBadge.tsx`
- Create: `web/components/RunCard.tsx`
- Create: `web/app/history/page.tsx`

- [ ] **Step 1: Implement the supporting components**

Create `web/components/Nav.tsx`:

```tsx
import Link from "next/link";

export default function Nav() {
  return (
    <nav style={{ padding: "12px 24px", borderBottom: "1px solid #e5e7eb",
                  display: "flex", gap: 16 }}>
      <strong>TradingAgents</strong>
      <Link href="/history">History</Link>
    </nav>
  );
}
```

Create `web/components/RatingBadge.tsx`:

```tsx
const COLORS: Record<string, string> = {
  Buy: "#16a34a",
  Overweight: "#22c55e",
  Hold: "#6b7280",
  Underweight: "#f97316",
  Sell: "#dc2626",
};

export default function RatingBadge({ rating }: { rating: string | null }) {
  if (!rating) return <span style={{ color: "#9ca3af" }}>—</span>;
  return (
    <span
      style={{
        background: COLORS[rating] ?? "#6b7280",
        color: "#fff",
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 12,
      }}
    >
      {rating}
    </span>
  );
}
```

Create `web/components/RunCard.tsx`:

```tsx
import Link from "next/link";
import type { RunOut } from "@/lib/types";
import RatingBadge from "./RatingBadge";

export default function RunCard({ run }: { run: RunOut }) {
  return (
    <Link href={`/history/${run.id}`} style={{ textDecoration: "none", color: "inherit" }}>
      <div style={{
        border: "1px solid #e5e7eb", borderRadius: 8, padding: 16,
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <div>
          <div style={{ fontWeight: 600 }}>{run.ticker}</div>
          <div style={{ fontSize: 12, color: "#6b7280" }}>{run.trade_date}</div>
        </div>
        <RatingBadge rating={run.final_rating} />
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: Implement the page**

Create `web/app/history/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RunCard from "@/components/RunCard";

export default async function HistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ ticker?: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/api/auth/signin");
  const { ticker } = await searchParams;
  const { items } = await api.listRuns(ticker);

  return (
    <>
      <Nav />
      <main style={{ padding: 24, maxWidth: 800, margin: "0 auto" }}>
        <h1>History</h1>
        <form>
          <input
            name="ticker"
            defaultValue={ticker ?? ""}
            placeholder="Filter by ticker (e.g. NVDA)"
            style={{ padding: 8, width: 240, marginBottom: 16 }}
          />
          <button type="submit" style={{ marginLeft: 8 }}>Filter</button>
        </form>
        {items.length === 0 ? (
          <p style={{ color: "#6b7280" }}>No runs yet. Run the importer or launch a new run (Wave 2).</p>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {items.map((r) => <RunCard key={r.id} run={r} />)}
          </div>
        )}
      </main>
    </>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run typecheck
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add web/components/ web/app/history/page.tsx
git commit -m "feat(web): add history list page"
```

---

## Task 16: `/history/[runId]` detail page with tabbed sections

**Files:**
- Create: `web/components/ReportTabs.tsx`
- Create: `web/app/history/[runId]/page.tsx`

- [ ] **Step 1: Implement `ReportTabs`**

Create `web/components/ReportTabs.tsx`:

```tsx
"use client";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReportSections } from "@/lib/types";

const ORDER: { key: keyof ReportSections; label: string }[] = [
  { key: "market", label: "Market" },
  { key: "sentiment", label: "Sentiment" },
  { key: "news", label: "News" },
  { key: "fundamentals", label: "Fundamentals" },
  { key: "investment_plan", label: "Research" },
  { key: "trader_plan", label: "Trader" },
  { key: "final", label: "Final" },
];

export default function ReportTabs({ sections }: { sections: ReportSections }) {
  const available = ORDER.filter((t) => sections[t.key]);
  const [active, setActive] = useState<keyof ReportSections | null>(
    available[0]?.key ?? null
  );
  if (!active) return <p style={{ color: "#6b7280" }}>No reports on disk for this run.</p>;
  return (
    <div>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e5e7eb",
                    marginBottom: 16, flexWrap: "wrap" }}>
        {available.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            style={{
              padding: "8px 12px", border: "none", background: "transparent",
              borderBottom: active === t.key ? "2px solid #2563eb" : "2px solid transparent",
              cursor: "pointer", fontWeight: active === t.key ? 600 : 400,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <article className="prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {sections[active] ?? ""}
        </ReactMarkdown>
      </article>
    </div>
  );
}
```

- [ ] **Step 2: Implement the page**

Create `web/app/history/[runId]/page.tsx`:

```tsx
import { redirect, notFound } from "next/navigation";
import { auth } from "@/lib/auth";
import { api } from "@/lib/api";
import Nav from "@/components/Nav";
import RatingBadge from "@/components/RatingBadge";
import ReportTabs from "@/components/ReportTabs";

export default async function RunDetailPage({
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
        <ReportTabs sections={run.report_sections} />
      </main>
    </>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run typecheck && npm run build
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add web/components/ReportTabs.tsx web/app/history/[runId]/
git commit -m "feat(web): add run detail page with tabbed markdown sections"
```

---

## Task 17: Dockerfiles + docker-compose

**Files:**
- Create: `server/Dockerfile`
- Create: `web/Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: Write `server/Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `web/Dockerfile`**

```dockerfile
FROM node:20-alpine AS base
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
```

- [ ] **Step 3: Write `.dockerignore`**

```
**/__pycache__
**/.pytest_cache
**/node_modules
**/.next
**/coverage
**/.env
**/.venv
```

- [ ] **Step 4: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: trading
      POSTGRES_PASSWORD: trading
      POSTGRES_DB: trading_dashboard
    volumes:
      - dbdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  api:
    build: ./server
    environment:
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      DATABASE_URL: postgresql+asyncpg://trading:trading@db:5432/trading_dashboard
      DASHBOARD_DATA_DIR: /data
    volumes:
      - dashdata:/data
    depends_on:
      - db
    ports:
      - "8000:8000"
    command: >
      sh -c "uv run alembic upgrade head &&
             uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"

  web:
    build: ./web
    environment:
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      NEXTAUTH_URL: ${NEXTAUTH_URL:-http://localhost:3000}
      AUTH_GITHUB_ID: ${AUTH_GITHUB_ID}
      AUTH_GITHUB_SECRET: ${AUTH_GITHUB_SECRET}
      API_BASE_URL: http://api:8000
    depends_on:
      - api
    ports:
      - "3000:3000"

volumes:
  dbdata:
  dashdata:
```

- [ ] **Step 5: Verify the build context works (no run, just build)**

```bash
docker compose build
```

Expected: both images build cleanly.

- [ ] **Step 6: Commit**

```bash
git add server/Dockerfile web/Dockerfile docker-compose.yml .dockerignore
git commit -m "feat: docker-compose stack (web + api + postgres)"
```

---

## Task 18: Playwright E2E smoke test

This test exercises the whole stack end-to-end: it boots `docker compose up`, seeds a User row + fixture markdown reports directly via `psql` + filesystem write, then drives a browser with a NextAuth-Credentials shim provider so we don't need real GitHub OAuth in CI.

**Files:**
- Create: `web/playwright.config.ts`
- Create: `web/tests/e2e/fixtures/seed.sql`
- Create: `web/tests/e2e/fixtures/seed.sh`
- Create: `web/tests/e2e/smoke.spec.ts`
- Modify: `web/lib/auth.ts` to conditionally add a test-only credentials provider when `E2E_TEST_MODE=1`.

- [ ] **Step 1: Add the test-only credentials provider gate**

Replace the entire contents of `web/lib/auth.ts` with:

```ts
import NextAuth, { type NextAuthConfig } from "next-auth";
import GitHub from "next-auth/providers/github";
import Credentials from "next-auth/providers/credentials";

const secret = process.env.NEXTAUTH_SECRET;
if (!secret) throw new Error("NEXTAUTH_SECRET is required");

const providers: NextAuthConfig["providers"] = [
  GitHub({
    clientId: process.env.AUTH_GITHUB_ID!,
    clientSecret: process.env.AUTH_GITHUB_SECRET!,
  }),
];

if (process.env.E2E_TEST_MODE === "1") {
  providers.push(
    Credentials({
      name: "e2e",
      credentials: { githubId: { label: "GitHub ID" } },
      async authorize(c) {
        if (!c?.githubId) return null;
        const id = String(c.githubId);
        return { id, email: `${id}@e2e.local` };
      },
    })
  );
}

export const authConfig: NextAuthConfig = {
  providers,
  session: { strategy: "jwt" },
  jwt: {
    // HS256 by default — matches server/app/auth.py
  },
  callbacks: {
    async jwt({ token, profile, user }) {
      // GitHub login (interactive): profile.id is numeric.
      if (profile && (profile as { id?: number | string }).id !== undefined) {
        token.sub = String((profile as { id: number | string }).id);
      } else if (user && process.env.E2E_TEST_MODE === "1") {
        // E2E credentials login: `user.id` is the supplied githubId.
        token.sub = String(user.id);
      }
      if (profile && (profile as { email?: string }).email) {
        token.email = (profile as { email: string }).email;
      } else if (user?.email) {
        token.email = user.email;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) (session.user as { githubId?: string }).githubId = token.sub;
      return session;
    },
  },
  secret,
};

export const { handlers, signIn, signOut, auth } = NextAuth(authConfig);
```

- [ ] **Step 2: Write the fixture seed script**

Create `web/tests/e2e/fixtures/seed.sql`:

```sql
INSERT INTO users (id, github_id, email, created_at)
VALUES ('11111111-2222-3333-4444-555555555555', 'e2e-user', 'e2e-user@e2e.local', NOW())
ON CONFLICT (github_id) DO NOTHING;

INSERT INTO runs (id, user_id, ticker, trade_date, status, final_rating,
                  results_path, created_at, completed_at)
VALUES ('22222222-3333-4444-5555-666666666666',
        '11111111-2222-3333-4444-555555555555',
        'NVDA', '2024-05-10', 'succeeded', 'Buy',
        '/data/users/11111111-2222-3333-4444-555555555555/NVDA/2024-05-10',
        NOW(), NOW())
ON CONFLICT (id) DO NOTHING;
```

Create `web/tests/e2e/fixtures/seed.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Run alembic, then seed Postgres + filesystem fixture.
docker compose exec -T api uv run alembic upgrade head
docker compose exec -T db psql -U trading -d trading_dashboard < seed.sql

USER_DIR=/data/users/11111111-2222-3333-4444-555555555555/NVDA/2024-05-10
docker compose exec -T api sh -c "
  mkdir -p ${USER_DIR}/reports/1_analysts &&
  echo '# market — NVDA' > ${USER_DIR}/reports/1_analysts/market.md &&
  echo '# final — BUY' > ${USER_DIR}/reports/final_trade_decision.md
"
```

Make it executable: `chmod +x web/tests/e2e/fixtures/seed.sh`.

- [ ] **Step 3: Write `web/playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    headless: true,
  },
});
```

- [ ] **Step 4: Write the smoke test**

Create `web/tests/e2e/smoke.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test("sign in via credentials provider and read a seeded run", async ({ page }) => {
  await page.goto("/api/auth/signin");
  await page.getByLabel("GitHub ID").fill("e2e-user");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/history/);
  await expect(page.getByText("NVDA")).toBeVisible();

  await page.getByText("NVDA").click();
  await expect(page.getByRole("heading", { name: /NVDA · 2024-05-10/i })).toBeVisible();
  await expect(page.getByText("market — NVDA")).toBeVisible();
});
```

- [ ] **Step 5: Run the smoke test**

```bash
# Bring up the stack with E2E mode
export NEXTAUTH_SECRET=$(openssl rand -base64 32)
export AUTH_GITHUB_ID=unused-in-e2e
export AUTH_GITHUB_SECRET=unused-in-e2e
export E2E_TEST_MODE=1
docker compose up -d --build
sleep 5
( cd web/tests/e2e/fixtures && ./seed.sh )
cd web && npx playwright install --with-deps chromium
npx playwright test
docker compose down
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add web/lib/auth.ts web/playwright.config.ts web/tests/e2e/
git commit -m "feat(web): add e2e smoke test with credentials provider gate"
```

---

## Task 19: Wave 1 closing — README touch-up and ship checklist

**Files:**
- Modify: `README.md` (append a small dashboard section)

- [ ] **Step 1: Append dashboard section to `README.md`**

Add at the end of `README.md`:

```markdown
## Dashboard (Wave 1)

A web dashboard for browsing TradingAgents runs lives under `server/`
(FastAPI) and `web/` (Next.js). See `docs/superpowers/specs/2026-05-17-trading-dashboard-design.md`
for design and `docs/superpowers/plans/2026-05-17-trading-dashboard-wave-1.md`
for the Wave 1 implementation plan.

Quick start:

```bash
cp server/.env.example server/.env
cp web/.env.example web/.env
# Fill in NEXTAUTH_SECRET (same value in both files) and GitHub OAuth creds.
docker compose up --build

# Optional: import existing CLI runs
docker compose exec api uv run python -m app.scripts.import_runs \
    --github-id <your-github-numeric-id> \
    --legacy-dir /host/path/to/.tradingagents/logs \
    --dashboard-dir /data
```

Read-only browsing only in Wave 1. Run launching, live monitoring, and
portfolio analytics arrive in Waves 2 and 3.
```

- [ ] **Step 2: Final sanity pass — run the full test suite**

```bash
cd server && uv run pytest -q
cd ../web && npm run typecheck
```

Expected: all server tests green, frontend type-check clean.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: link dashboard wave 1 from readme"
```

---

## Wave 1 — Done. What ships:

- **Server**: FastAPI with health, `/me`, `/runs`, `/runs/{id}` endpoints; JWT-verified auth; SQLAlchemy async + Alembic; `user_root` security primitive with adversarial test coverage.
- **Frontend**: Next.js App Router with NextAuth GitHub provider, typed FastAPI client, history list + run detail pages with tabbed markdown rendering.
- **Operations**: Docker Compose for web + api + Postgres; legacy importer script; Playwright E2E smoke.
- **Tests**: ~30 unit/integration tests in `server/tests/`, 1 Playwright e2e covering the happy path.

## Next:

- **Wave 2 plan** (`docs/superpowers/plans/YYYY-MM-DD-trading-dashboard-wave-2.md`) will add: arq worker, `POST /runs`, file-tail endpoint, LiveLogStream React component, launch form, orphan sweeper cron.
- **Wave 3 plan** will add: memory_mirror, portfolio_calc (Sharpe / win rate / max DD), P&L curve, per-ticker chart with yfinance price overlay.

Each wave is independently deployable and provides standalone value.

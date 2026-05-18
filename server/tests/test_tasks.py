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
    """Stand-in for TradingAgentsGraph. Writes a fake report + log.

    NOTE: signature mirrors what `tasks.py:run_propagate` actually calls.
    If the production call site adds a new arg, update this stub so the
    test fails loudly instead of silently accepting the extra arg.
    """

    # Node names the stub pretends to execute; matches the real graph's
    # analyst tier so a test can assert these specific names land in the log.
    NODES = ("market_analyst", "social_analyst", "news_analyst", "fundamentals_analyst")

    def __init__(self, *, selected_analysts, config, **_kwargs):
        self.config = config
        self.selected_analysts = selected_analysts

    def propagate(self, company_name, trade_date, *, progress_callback=None):
        # `progress_callback` mirrors the production signature added for v3+ #9.
        # If the production call site stops passing it, this stub's `[node]`
        # lines will stop appearing in the log and the per-node-progress test
        # below will fail loudly.
        results = Path(self.config["results_dir"]) / company_name / trade_date
        (results / "reports" / "1_analysts").mkdir(parents=True, exist_ok=True)
        (results / "reports" / "1_analysts" / "market.md").write_text("# market")
        (results / "reports" / "final_trade_decision.md").write_text("# final\n\n**Rating**: Buy")
        log = results / "message_tool.log"
        log.write_text("step 1\nstep 2\n")
        if progress_callback is not None:
            for node_name in self.NODES:
                progress_callback(node_name)
        return {"market_report": "# market", "final_trade_decision": "# final"}, "Buy"


class FailingGraph(StubGraph):
    def propagate(self, *a, **kw):
        raise RuntimeError("simulated llm error")


def _factory_yielding(session):
    """Returns a callable that, when called, returns an async-context-manager
    yielding the supplied session. Mimics async_sessionmaker calls."""
    class _Wrapper:
        async def __aenter__(self_):
            return session

        async def __aexit__(self_, *exc):
            return False

    def _factory():
        return _Wrapper()

    return _factory


@pytest.mark.asyncio
async def test_run_propagate_marks_succeeded(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: StubGraph(**kw))
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker",
                        _factory_yielding(db_session))

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
                        _factory_yielding(db_session))

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


import time as _time


class SlowGraph(StubGraph):
    """Stub that blocks long enough for ≥2 heartbeat ticks at a short interval."""

    def propagate(self, company_name, trade_date, *, progress_callback=None):
        results = Path(self.config["results_dir"]) / company_name / trade_date
        (results / "reports" / "1_analysts").mkdir(parents=True, exist_ok=True)
        (results / "reports" / "1_analysts" / "market.md").write_text("# market")
        (results / "reports" / "final_trade_decision.md").write_text("# final\n\n**Rating**: Buy")
        log = results / "message_tool.log"
        log.write_text("step 1\n")
        _time.sleep(0.3)  # block long enough for the heartbeat interval (0.1s) to fire 2-3 times
        return {"market_report": "# market", "final_trade_decision": "# final"}, "Buy"


@pytest.mark.asyncio
async def test_run_propagate_heartbeat_updates_last_heartbeat_at(tmp_path, monkeypatch):
    """Heartbeat loop must update last_heartbeat_at while propagate() is running.

    Uses its own engine/session factory backed by a file-based SQLite database
    so the heartbeat loop can issue independent commits without conflicting with
    the main task's session (in-memory SQLite gives each connection a new DB).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.base import Base

    db_file = tmp_path / "test_hb.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: SlowGraph(**kw))
    monkeypatch.setattr(worker_tasks, "_session_factory_for_worker", session_factory)

    # Patch get_settings to inject a fast heartbeat interval.
    from app.config import get_settings as _gs
    real = _gs()
    _gs.cache_clear()

    class _FakeSettings:
        def __getattr__(self, name):
            if name == "heartbeat_interval_seconds":
                return 0.1
            return getattr(real, name)

    monkeypatch.setattr(worker_tasks, "get_settings", lambda: _FakeSettings())

    uid = uuid.uuid4()
    run_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(User(id=uid, github_id="gh-hb"))
        session.add(
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
        await session.commit()

    await worker_tasks.run_propagate({"redis": MagicMock()}, str(run_id))

    async with session_factory() as session:
        found = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()

    await engine.dispose()

    assert found.status is RunStatus.SUCCEEDED
    # The heartbeat should have fired at least once during the 0.3s SlowGraph sleep
    # at 0.1s interval. last_heartbeat_at gets set to a non-trivial value.
    assert found.last_heartbeat_at is not None
    # And the log file should contain a [heartbeat] line written by the heartbeat loop.
    log_text = (tmp_path / "NVDA" / "2024-05-10" / "message_tool.log").read_text()
    assert "[heartbeat]" in log_text


@pytest.mark.asyncio
async def test_run_propagate_invokes_memory_mirror_on_success(
    db_session, tmp_path, monkeypatch
):
    """After a successful propagate, the worker syncs memory_mirror for the user."""
    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: StubGraph(**kw))
    monkeypatch.setattr(
        worker_tasks, "_session_factory_for_worker", _factory_yielding(db_session)
    )

    calls: list[tuple] = []

    async def fake_sync_user(session, *, dashboard_dir, user_id):
        calls.append((dashboard_dir, user_id))
        return 1

    monkeypatch.setattr(worker_tasks, "_memory_mirror_sync", fake_sync_user)

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-mm-w"))
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

    assert len(calls) == 1
    _dir, called_uid = calls[0]
    assert called_uid == uid


@pytest.mark.asyncio
async def test_run_propagate_writes_per_node_progress_to_log(
    db_session, tmp_path, monkeypatch
):
    """v3+ followup #9: run_propagate must pass a progress_callback to
    graph.propagate() so each LangGraph node transition writes a `[node] X`
    line to message_tool.log — the live monitor then shows actual graph
    activity instead of just heartbeat ticks between [start] and [completed].
    """
    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: StubGraph(**kw))
    monkeypatch.setattr(
        worker_tasks, "_session_factory_for_worker", _factory_yielding(db_session)
    )

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-stream"))
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

    log_text = (tmp_path / "NVDA" / "2024-05-10" / "message_tool.log").read_text()
    for node_name in StubGraph.NODES:
        assert f"[node] {node_name}" in log_text, (
            f"expected [node] {node_name} in message_tool.log; got:\n{log_text}"
        )


@pytest.mark.asyncio
async def test_run_propagate_mirror_failure_does_not_fail_run(
    db_session, tmp_path, monkeypatch
):
    """A mirror exception must be swallowed; the run still marks SUCCEEDED."""
    monkeypatch.setattr(worker_tasks, "_graph_factory", lambda **kw: StubGraph(**kw))
    monkeypatch.setattr(
        worker_tasks, "_session_factory_for_worker", _factory_yielding(db_session)
    )

    async def boom(session, *, dashboard_dir, user_id):
        raise RuntimeError("mirror exploded")

    monkeypatch.setattr(worker_tasks, "_memory_mirror_sync", boom)

    uid = uuid.uuid4()
    db_session.add(User(id=uid, github_id="gh-mm-w2"))
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

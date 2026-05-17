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

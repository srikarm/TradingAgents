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

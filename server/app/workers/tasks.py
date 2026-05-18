"""arq worker tasks.

This module is the ONLY place that imports from the root tradingagents
package. The api process never imports from here directly — it enqueues
by name via the arq pool.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.config import get_settings
from app.db import get_session_factory
from app.models.run import Run, RunStatus
from app.services.memory_mirror import sync_user as _memory_mirror_sync_impl

logger = logging.getLogger(__name__)


def _graph_factory(**kwargs):
    """Indirection so tests can patch in a stub TradingAgentsGraph."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(**kwargs)


async def _memory_mirror_sync(session, *, dashboard_dir, user_id):
    """Indirection so tests can patch the mirror behavior."""
    return await _memory_mirror_sync_impl(
        session, dashboard_dir=dashboard_dir, user_id=user_id
    )


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


def _append_log(path: Path, message: str) -> None:
    """Append a timestamped line to message_tool.log. Creates parent dirs + file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")


def _persist_reports(run_path: Path, final_state: dict) -> None:
    """Write the markdown reports from final_state to disk.

    Mirrors the layout used by cli/main.py:save_report_to_disk so the
    existing GET /runs/{id} endpoint can read them via load_report_sections.
    """
    reports = run_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    analysts = reports / "1_analysts"
    research = reports / "2_research"
    trading = reports / "3_trading"

    for section_key, rel_path in [
        ("market_report", analysts / "market.md"),
        ("sentiment_report", analysts / "sentiment.md"),
        ("news_report", analysts / "news.md"),
        ("fundamentals_report", analysts / "fundamentals.md"),
    ]:
        text = final_state.get(section_key)
        if text:
            rel_path.parent.mkdir(parents=True, exist_ok=True)
            rel_path.write_text(text, encoding="utf-8")

    debate = final_state.get("investment_debate_state") or {}
    judge = debate.get("judge_decision")
    if judge:
        research.mkdir(parents=True, exist_ok=True)
        (research / "manager.md").write_text(judge, encoding="utf-8")

    trader_plan = final_state.get("trader_investment_plan")
    if trader_plan:
        trading.mkdir(parents=True, exist_ok=True)
        (trading / "trader.md").write_text(trader_plan, encoding="utf-8")

    final = final_state.get("final_trade_decision")
    if final:
        (reports / "final_trade_decision.md").write_text(final, encoding="utf-8")


async def _heartbeat_loop(session_factory, run_id: uuid.UUID, interval: int, log_path: Path) -> None:
    """Update Run.last_heartbeat_at every `interval` seconds until cancelled.

    Also appends a timestamped tick to the worker's message_tool.log so the
    live monitor shows progress between propagate() phases. Log-write failures
    are reported the first few times then suppressed to avoid spamming stderr
    on a full disk.
    """
    log_failures = 0
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
        except Exception:  # noqa: BLE001
            logger.exception("heartbeat update failed for run_id=%s", run_id)
        try:
            _append_log(log_path, "[heartbeat] still running")
            log_failures = 0
        except Exception:  # noqa: BLE001
            log_failures += 1
            if log_failures <= 3:
                logger.exception("heartbeat log append failed for run_id=%s (failure %d)", run_id, log_failures)
            # silently skip further log writes; heartbeat DB update still proceeds.


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
        results_path = Path(run.results_path)
        config = _build_config(run)

    # Set up the per-run results directory and message_tool.log path.
    # The Run.results_path is <user_dir>/<ticker>/<date> — that's where we
    # write both the log and (after propagate) the reports.
    log_path = results_path / "message_tool.log"
    _append_log(log_path, f"[start] launching propagate for {ticker} on {trade_date}")

    heartbeat = asyncio.create_task(
        _heartbeat_loop(session_factory, run_id, settings.heartbeat_interval_seconds, log_path)
    )

    error_summary: str | None = None
    error_detail: str | None = None
    final_rating: str | None = None
    try:
        graph = _graph_factory(
            selected_analysts=["market", "social", "news", "fundamentals"],
            config=config,
        )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: graph.propagate(ticker, trade_date)
        )
        if isinstance(result, tuple) and len(result) == 2:
            final_state, decision = result
            final_rating = str(decision).split()[0] if decision else None
            _persist_reports(results_path, final_state)
        _append_log(log_path, f"[completed] final_rating={final_rating}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        logger.exception("run_propagate failed for run_id=%s", run_id)
        error_summary = str(exc)[:500]
        error_detail = traceback.format_exc()[:8000]
        _append_log(log_path, f"[failed] {error_summary}")
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

    # Third transaction: refresh the portfolio mirror for this user. Failures
    # here are non-fatal — the run is already marked complete and the user can
    # still browse it; portfolio will catch up on the next per-request sync.
    if error_summary is None:
        try:
            async with session_factory() as session:
                run_for_mirror = (
                    await session.execute(select(Run).where(Run.id == run_id))
                ).scalar_one_or_none()
                if run_for_mirror is not None:
                    mirror_count = await _memory_mirror_sync(
                        session,
                        dashboard_dir=settings.dashboard_data_dir,
                        user_id=run_for_mirror.user_id,
                    )
                    if mirror_count == 0:
                        # Either lock was held by a concurrent sync (warning
                        # already logged from sync_user) or disk had no
                        # entries. Surface run_id so operators can grep.
                        logger.warning(
                            "memory_mirror post-run sync produced 0 entries "
                            "for run_id=%s user_id=%s",
                            run_id, run_for_mirror.user_id,
                        )
        except Exception:  # noqa: BLE001
            logger.exception("memory_mirror sync failed for run_id=%s", run_id)


async def orphan_sweeper(ctx: dict) -> None:
    """Cron: mark stale RUNNING + stale QUEUED rows as failed.

    Two sequential sweeps in one transaction:
    - RUNNING: heartbeat older than orphan_threshold_seconds → worker
      died mid-run. Marked FAILED with error_summary='worker_lost'.
    - QUEUED:  created_at older than queued_threshold_seconds → worker
      never picked it up. Marked FAILED with error_summary='never_picked_up'.

    The two summaries are distinguishable so operators can triage:
    'worker_lost' points at process/OOM/segfault investigation;
    'never_picked_up' points at arq/Redis/worker-registration.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    running_threshold = now - timedelta(seconds=settings.orphan_threshold_seconds)
    queued_threshold = now - timedelta(seconds=settings.queued_threshold_seconds)
    try:
        async with _session_factory_for_worker() as session:
            running_result = await session.execute(
                update(Run)
                .where(
                    Run.status == RunStatus.RUNNING,
                    Run.last_heartbeat_at < running_threshold,
                )
                .values(
                    status=RunStatus.FAILED,
                    error_summary="worker_lost",
                    completed_at=now,
                )
            )
            queued_result = await session.execute(
                update(Run)
                .where(
                    Run.status == RunStatus.QUEUED,
                    Run.created_at < queued_threshold,
                )
                .values(
                    status=RunStatus.FAILED,
                    error_summary="never_picked_up",
                    completed_at=now,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        # Surface DB failures on the app.workers.tasks logger with
        # orphan_sweeper context — arq's framework-level logger names the
        # cron but doesn't tell an operator watching the app log what failed.
        # Re-raise so arq still marks the cron tick failed for its accounting.
        logger.exception("orphan_sweeper: DB sweep failed")
        raise

    running_n = running_result.rowcount
    queued_n = queued_result.rowcount
    if running_n or queued_n:
        logger.warning(
            "orphan_sweeper: marked %d stuck-running + %d stuck-queued run(s) failed",
            running_n,
            queued_n,
        )
    else:
        logger.debug("orphan_sweeper: no stale runs found")

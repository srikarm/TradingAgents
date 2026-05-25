"""Seed deterministic fixture data for the Playwright e2e suite / CI.

Creates the canonical `e2e-user` (the identity the E2E_TEST_MODE credentials
login resolves to — by email) and the backend state the data-dependent specs
need:

- smoke.spec / ticker-chart.spec: a SUCCEEDED NVDA run for 2024-05-10 with
  on-disk report sections (so /history shows NVDA and the run detail renders
  "market — NVDA").
- portfolio.spec: >=1 RESOLVED MemoryEntry with raw_return (so /portfolio
  computes win-rate / Sharpe / drawdown). memory_mirror.sync_user is a pure
  upsert from disk and no-ops when there's no trading_memory.md, so these
  directly-inserted rows survive the portfolio page's on-load sync.
- ticker-chart.spec: NVDA MemoryEntry rows feed the decision markers (prices
  come from yfinance and degrade gracefully if unavailable in CI).

Idempotent: re-running updates in place. Run with:
    uv run python -m app.scripts.seed_e2e
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session_factory
from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.services.user_root import user_run_dir

E2E_EMAIL = "e2e-user@e2e.local"
E2E_GITHUB_ID = "e2e-user"
E2E_USER_ID = uuid.UUID("e2e0e2e0-0000-4000-8000-000000000001")  # fixed, deterministic

REPORTS = {
    "1_analysts/market.md": "# Market Analysis — NVDA\n\nSeeded e2e market report. Trend is constructive.\n",
    "1_analysts/sentiment.md": "# Sentiment — NVDA\n\nSeeded e2e sentiment report.\n",
    "1_analysts/news.md": "# News — NVDA\n\nSeeded e2e news report.\n",
    "1_analysts/fundamentals.md": "# Fundamentals — NVDA\n\nSeeded e2e fundamentals report.\n",
    "2_research/manager.md": "# Research Manager — NVDA\n\nSeeded e2e investment plan.\n",
    "3_trading/trader.md": "# Trader Plan — NVDA\n\nSeeded e2e trader plan.\n",
    "final_trade_decision.md": "FINAL TRANSACTION PROPOSAL: **BUY**\n\nSeeded e2e final decision.\n",
}

# (ticker, trade_date, rating, raw_return, alpha, holding_days, decision)
MEMORY = [
    ("NVDA", "2024-05-10", "BUY", 0.062, 0.041, 7, "Seeded: bought NVDA on momentum."),
    ("NVDA", "2024-04-12", "HOLD", 0.015, -0.004, 14, "Seeded: held through earnings."),
    ("AAPL", "2024-04-20", "SELL", -0.023, -0.012, 5, "Seeded: trimmed AAPL into weakness."),
]


def _write_reports(results_path: Path) -> None:
    reports = results_path / "reports"
    for rel, body in REPORTS.items():
        f = reports / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")


async def _seed() -> None:
    settings = get_settings()
    dashboard_dir = Path(settings.dashboard_data_dir)
    now = datetime.now(timezone.utc)
    factory = get_session_factory()

    async with factory() as session:
        # --- user (resolved by email at login) ---
        user = (
            await session.execute(select(User).where(User.email == E2E_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            user = User(id=E2E_USER_ID, github_id=E2E_GITHUB_ID, email=E2E_EMAIL)
            session.add(user)
            await session.flush()
        uid = user.id

        # --- SUCCEEDED NVDA run + on-disk reports ---
        run = (
            await session.execute(
                select(Run).where(
                    Run.user_id == uid, Run.ticker == "NVDA", Run.trade_date == "2024-05-10"
                )
            )
        ).scalar_one_or_none()
        results_path = user_run_dir(dashboard_dir, str(uid), "NVDA", "2024-05-10")
        if run is None:
            run = Run(
                id=uuid.uuid4(),
                user_id=uid,
                ticker="NVDA",
                trade_date="2024-05-10",
                status=RunStatus.SUCCEEDED,
                final_rating="BUY",
                results_path=str(results_path),
                created_at=now,
                completed_at=now,
                triggered_by="manual",
            )
            session.add(run)
        else:
            run.status = RunStatus.SUCCEEDED
            run.final_rating = "BUY"
            run.completed_at = now
        _write_reports(results_path)

        # --- RESOLVED memory entries (portfolio + ticker decisions) ---
        for ticker, td, rating, raw, alpha, hold, decision in MEMORY:
            existing = (
                await session.execute(
                    select(MemoryEntry).where(
                        MemoryEntry.user_id == uid,
                        MemoryEntry.ticker == ticker,
                        MemoryEntry.trade_date == td,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    MemoryEntry(
                        id=uuid.uuid4(),
                        user_id=uid,
                        ticker=ticker,
                        trade_date=td,
                        rating=rating,
                        status=MemoryEntryStatus.RESOLVED,
                        raw_return=raw,
                        alpha_return=alpha,
                        holding_days=hold,
                        decision_text=decision,
                        reflection_text="Seeded reflection.",
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                existing.rating = rating
                existing.status = MemoryEntryStatus.RESOLVED
                existing.raw_return = raw
                existing.alpha_return = alpha
                existing.holding_days = hold
                existing.decision_text = decision

        await session.commit()
        print(f"seeded e2e fixture: user={uid} email={E2E_EMAIL} run=NVDA/2024-05-10 + {len(MEMORY)} memory entries")


def main() -> int:
    asyncio.run(_seed())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

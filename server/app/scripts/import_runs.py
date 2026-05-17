"""One-shot CLI: import legacy ``~/.tradingagents/logs`` runs into a
per-user dashboard namespace.

Usage:
    uv run python -m app.scripts.import_runs \\
        --github-id <gh-username> \\
        --legacy-dir ~/.tradingagents/logs \\
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

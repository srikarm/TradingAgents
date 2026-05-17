from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models.memory_entry import MemoryEntry
from app.models.user import User
from app.schemas.portfolio import (
    PnLPoint,
    PortfolioCurveOut,
    PortfolioSummaryOut,
)
from app.services import memory_mirror, portfolio_calc

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# Indirection so tests can patch the per-request mirror sync to a noop.
async def _sync_user(session, *, dashboard_dir, user_id):
    return await memory_mirror.sync_user(
        session, dashboard_dir=dashboard_dir, user_id=user_id
    )


async def _load_entries(session: AsyncSession, user_id) -> list[dict]:
    rows = (
        await session.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == user_id)
        )
    ).scalars().all()
    return [
        {
            "ticker": r.ticker,
            "trade_date": r.trade_date,
            "rating": r.rating,
            "status": r.status.value,
            "raw_return": r.raw_return,
            "alpha_return": r.alpha_return,
            "holding_days": r.holding_days,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/summary", response_model=PortfolioSummaryOut)
async def get_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioSummaryOut:
    settings = get_settings()
    try:
        await _sync_user(db, dashboard_dir=settings.dashboard_data_dir, user_id=user.id)
    except Exception:  # noqa: BLE001
        pass  # mirror failure is non-fatal; read whatever's there
    entries = await _load_entries(db, user.id)
    return PortfolioSummaryOut(**portfolio_calc.summary(entries))


@router.get("/curve", response_model=PortfolioCurveOut)
async def get_curve(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioCurveOut:
    settings = get_settings()
    try:
        await _sync_user(db, dashboard_dir=settings.dashboard_data_dir, user_id=user.id)
    except Exception:  # noqa: BLE001
        pass
    entries = await _load_entries(db, user.id)
    pts = portfolio_calc.cumulative_curve(entries)
    return PortfolioCurveOut(points=[PnLPoint(**p) for p in pts])

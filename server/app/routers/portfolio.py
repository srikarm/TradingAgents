from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models.memory_entry import MemoryEntry
from app.models.user import User
from app.schemas.portfolio import (
    DecisionPin,
    PnLPoint,
    PortfolioCurveOut,
    PortfolioSummaryOut,
    PricePoint,
    TickerDetailOut,
)
from app.services import memory_mirror, portfolio_calc, price_cache

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _fetch_prices(*a, **kw):
    """Indirection so tests can patch the price fetch."""
    return await price_cache.fetch_prices(*a, **kw)


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


@router.get("/ticker/{ticker}", response_model=TickerDetailOut)
async def get_ticker_detail(
    ticker: str = PathParam(..., pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TickerDetailOut:
    settings = get_settings()
    try:
        await _sync_user(db, dashboard_dir=settings.dashboard_data_dir, user_id=user.id)
    except Exception:  # noqa: BLE001
        pass

    rows = (
        await db.execute(
            select(MemoryEntry)
            .where(MemoryEntry.user_id == user.id, MemoryEntry.ticker == ticker)
            .order_by(MemoryEntry.trade_date)
        )
    ).scalars().all()

    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    dates = sorted(r.trade_date for r in rows)
    start = (datetime.strptime(dates[0], "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    end = (datetime.strptime(dates[-1], "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")

    decisions = [
        DecisionPin(
            trade_date=r.trade_date,
            rating=r.rating,
            status=r.status.value,
            raw_return=r.raw_return,
        )
        for r in rows
    ]

    try:
        price_points = await _fetch_prices(
            settings.dashboard_data_dir,
            user_id=user.id,
            ticker=ticker,
            start=start,
            end=end,
        )
    except price_cache.PriceFetchError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "price_data_unavailable", "ticker": ticker},
        )

    return TickerDetailOut(
        ticker=ticker,
        prices=[PricePoint(**p) for p in price_points],
        decisions=decisions,
    )

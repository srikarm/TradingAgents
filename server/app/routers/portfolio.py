from __future__ import annotations

import logging
from datetime import datetime, timedelta

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as PathParam
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.models.memory_entry import MemoryEntry
from app.models.user import User
from app.schemas.portfolio import (
    DecisionPin,
    OHLCVBar,
    PnLPoint,
    PortfolioCurveOut,
    PortfolioSummaryOut,
    TickerDetailOut,
)
from app.services import memory_mirror, portfolio_calc, price_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _fetch_prices(*a, **kw):
    """Indirection so tests can patch the price fetch."""
    return await price_cache.fetch_prices(*a, **kw)


# Indirection so tests can patch the per-request mirror sync to a noop.
async def _sync_user(session, *, dashboard_dir, user_id):
    return await memory_mirror.sync_user(
        session, dashboard_dir=dashboard_dir, user_id=user_id
    )


async def _sync_user_safe(db: AsyncSession, dashboard_dir, user_id) -> None:
    """Run the per-request mirror sync, logging + rolling back on DB failure.

    Mirror failure is non-fatal — the user still gets whatever's already in
    Postgres. If sync_user raises a SQLAlchemyError mid-loop, the session is
    left in an aborted-transaction state and the subsequent _load_entries()
    call would also fail unexpectedly; rollback resets it. Non-DB exceptions
    don't affect session state, so we just log them and continue.
    """
    try:
        await _sync_user(db, dashboard_dir=dashboard_dir, user_id=user_id)
    except SQLAlchemyError:
        logger.warning(
            "portfolio mirror sync failed (DB error) for user_id=%s",
            user_id, exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("rollback after sync failure also failed")
    except Exception:  # noqa: BLE001
        logger.warning(
            "portfolio mirror sync failed for user_id=%s", user_id, exc_info=True
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
    await _sync_user_safe(db, settings.dashboard_data_dir, user.id)
    entries = await _load_entries(db, user.id)
    return PortfolioSummaryOut(**portfolio_calc.summary(entries))


@router.get("/curve", response_model=PortfolioCurveOut)
async def get_curve(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortfolioCurveOut:
    settings = get_settings()
    await _sync_user_safe(db, settings.dashboard_data_dir, user.id)
    entries = await _load_entries(db, user.id)
    pts = portfolio_calc.cumulative_curve(entries)
    return PortfolioCurveOut(points=[PnLPoint(**p) for p in pts])


@router.get("/ticker/{ticker}", response_model=TickerDetailOut)
async def get_ticker_detail(
    ticker: str = PathParam(..., pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$"),
    interval: Literal["1d", "1h"] = Query("1d"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TickerDetailOut:
    settings = get_settings()
    await _sync_user_safe(db, settings.dashboard_data_dir, user.id)

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

    # DecisionPin enforces the (status='pending' ⟹ raw_return IS NULL)
    # invariant via @model_validator. If any DB row violates it (e.g.,
    # direct SQL INSERT, future endpoint bypassing the parser), the
    # construction raises ValidationError — without the explicit catch
    # below, a single corrupt row would 500 the entire endpoint and
    # produce no log context about which row caused it. Logging the
    # offending trade_dates + user lets operators locate the row quickly.
    try:
        decisions = [
            DecisionPin(
                trade_date=r.trade_date,
                rating=r.rating,
                status=r.status.value,
                raw_return=r.raw_return,
            )
            for r in rows
        ]
    except ValidationError:
        logger.error(
            "DecisionPin invariant violated for user_id=%s ticker=%s — "
            "DB row(s) have status='pending' with raw_return IS NOT NULL "
            "(or other schema violation); inspect trade_dates: %s",
            user.id, ticker, [r.trade_date for r in rows],
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal data integrity error.",
        ) from None

    try:
        price_points, data_range_clipped = await _fetch_prices(
            settings.dashboard_data_dir,
            user_id=user.id,
            ticker=ticker,
            start=start,
            end=end,
            interval=interval,
        )
    except price_cache.PriceFetchError:
        # Spec §6: UI shows decision list without price overlay when yfinance
        # fails. Return 200 with empty prices so the user keeps their decision
        # history — the frontend renders a placeholder banner where the chart
        # would be.
        logger.warning(
            "yfinance fetch failed for user_id=%s ticker=%s; returning decisions only",
            user.id, ticker, exc_info=True,
        )
        price_points = []
        data_range_clipped = False

    return TickerDetailOut(
        ticker=ticker,
        prices=[OHLCVBar(**p) for p in price_points],
        decisions=decisions,
        data_range_clipped=data_range_clipped,
    )

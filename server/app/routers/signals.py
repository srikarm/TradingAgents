from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.run import Run
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.signal import SignalListOut, SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/today", response_model=SignalListOut)
async def signals_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SignalListOut:
    """Today's monitor-dispatched signals for the current user, ranked by
    actionability (BUY < SELL < in-flight < HOLD < FAILED)."""
    if not user.briefing_tz:
        return SignalListOut(items=[], trade_date=None)

    tz = ZoneInfo(user.briefing_tz)
    today_local = datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")

    rank = case(
        (Run.final_rating == "BUY", 0),
        (Run.final_rating == "SELL", 1),
        (Run.final_rating.is_(None), 2),
        (Run.final_rating == "HOLD", 3),
        (Run.status == "failed", 4),
        else_=5,
    )

    stmt = (
        select(Run, WatchlistItem.notes)
        .join(
            WatchlistItem,
            (WatchlistItem.user_id == Run.user_id)
            & (WatchlistItem.ticker == Run.ticker),
            isouter=True,
        )
        .where(
            Run.user_id == user.id,
            Run.triggered_by == "monitor",
            Run.trade_date == today_local,
        )
        .order_by(rank, Run.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    items = [
        SignalOut(
            run_id=run.id,
            ticker=run.ticker,
            trade_date=run.trade_date,
            status=run.status.value if hasattr(run.status, "value") else run.status,
            final_rating=run.final_rating,
            created_at=run.created_at,
            completed_at=run.completed_at,
            notes=notes,
        )
        for (run, notes) in rows
    ]
    return SignalListOut(items=items, trade_date=today_local)

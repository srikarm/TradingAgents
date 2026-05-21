import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.watchlist import (
    WatchlistAdd,
    WatchlistItemOut,
    WatchlistNotesUpdate,
)
from app.services.user_root import TICKER_RE, check_segment

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistItem]:
    """Return user's watchlist, newest-added first."""
    result = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.added_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=WatchlistItemOut, status_code=201)
async def add_to_watchlist(
    body: WatchlistAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Add a ticker to the watchlist. 409 on duplicate, 422 on invalid ticker."""
    try:
        check_segment("ticker", body.ticker, TICKER_RE)
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "invalid ticker", "ticker": body.ticker})

    item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user.id,
        ticker=body.ticker,
        notes=body.notes,
        # Set added_at in Python (microsecond-precise) rather than relying on
        # server_default — SQLite's CURRENT_TIMESTAMP has only second
        # resolution, so rapid back-to-back POSTs would tie and lose the
        # "most recent first" ordering contract. Same pattern as
        # services/run_dispatcher.py sets Run.created_at.
        added_at=datetime.now(timezone.utc),
    )
    db.add(item)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "ticker already on watchlist", "ticker": body.ticker},
        )
    return item


@router.patch("/{ticker}", response_model=WatchlistItemOut)
async def update_notes(
    body: WatchlistNotesUpdate,
    ticker: str = PathParam(..., pattern=TICKER_RE.pattern),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Replace notes for a watched ticker."""
    item = (
        await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user.id,
                WatchlistItem.ticker == ticker,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=404, detail={"error": "ticker not on watchlist"}
        )
    item.notes = body.notes
    return item


@router.delete("/{ticker}", status_code=204)
async def remove_from_watchlist(
    ticker: str = PathParam(..., pattern=TICKER_RE.pattern),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a ticker from the user's watchlist."""
    result = await db.execute(
        sa.delete(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=404, detail={"error": "ticker not on watchlist"}
        )

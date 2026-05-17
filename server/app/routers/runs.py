from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.run import Run
from app.models.user import User
from app.schemas.run import RunListOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunListOut)
async def list_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    ticker: str | None = Query(default=None, max_length=12),
    limit: int = Query(default=50, ge=1, le=200),
) -> RunListOut:
    stmt = (
        select(Run)
        .where(Run.user_id == user.id)
        .order_by(Run.trade_date.desc(), Run.created_at.desc())
        .limit(limit)
    )
    if ticker:
        stmt = stmt.where(Run.ticker == ticker.upper())
    rows = (await db.execute(stmt)).scalars().all()
    return RunListOut(items=[RunOut.model_validate(r) for r in rows])

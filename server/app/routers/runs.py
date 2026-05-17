import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.run import Run
from app.models.user import User
from app.schemas.run import RunDetailOut, RunListOut, RunOut
from app.services.run_loader import load_report_sections

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


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(
    run_id: _uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunDetailOut:
    run = (
        await db.execute(
            select(Run).where(Run.id == run_id, Run.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    sections = load_report_sections(run.results_path)
    return RunDetailOut.model_validate(
        {**run.__dict__, "report_sections": sections.model_dump()}
    )

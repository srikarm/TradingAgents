from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.monitor import MonitorOut, MonitorUpdate
from app.schemas.user import UserOut
from app.services.monitor import compute_next_briefing_at

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me/monitor", response_model=MonitorOut)
async def update_monitor(
    body: MonitorUpdate = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorOut:
    """Enable/disable the monitor cron + persist briefing time + tz.

    Enabling requires both briefing_time_local and briefing_tz to be set
    (either in this request or already on the user record). Disabling
    preserves the existing time + tz so re-enabling restores prior config.
    """
    # Determine the post-update values so we can validate before writing.
    new_time = body.briefing_time_local if body.briefing_time_local is not None else user.briefing_time_local
    new_tz = body.briefing_tz if body.briefing_tz is not None else user.briefing_tz
    if body.enabled and (new_time is None or new_tz is None):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "briefing_time_local and briefing_tz are required when enabling"
            },
        )
    user.monitor_enabled = body.enabled
    if body.briefing_time_local is not None:
        user.briefing_time_local = body.briefing_time_local
    if body.briefing_tz is not None:
        user.briefing_tz = body.briefing_tz
    await db.commit()
    await db.refresh(user)
    return MonitorOut(
        enabled=user.monitor_enabled,
        briefing_time_local=user.briefing_time_local,
        briefing_tz=user.briefing_tz,
        next_briefing_at=compute_next_briefing_at(user, datetime.now(timezone.utc)),
    )

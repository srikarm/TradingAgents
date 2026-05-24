from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.models.user import User
from app.schemas.monitor import MonitorOut, MonitorUpdate
from app.schemas.notification import NotifyOut, NotifyUpdate
from app.schemas.user import UserOut
from app.services.monitor import compute_next_briefing_at

router = APIRouter(tags=["me"])


def _deliverable(user: User) -> bool:
    """Can the user's chosen channel actually reach them right now?

    Email requires an address on record. webpush/none are not live-deliverable
    in v1 (no subscription store yet), so they report False.
    """
    if user.notify_channel == "email":
        return bool(user.email)
    return False


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/me/notifications", response_model=NotifyOut)
async def get_notifications(user: User = Depends(get_current_user)) -> NotifyOut:
    return NotifyOut(
        enabled=user.notify_enabled,
        channel=user.notify_channel,
        threshold=user.notify_threshold,
        deliverable=_deliverable(user),
    )


@router.patch("/me/notifications", response_model=NotifyOut)
async def update_notifications(
    body: NotifyUpdate = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotifyOut:
    """Enable/disable out-of-band notifications + persist channel + threshold.

    Mirrors the /me/monitor PATCH contract: fields omitted from the body fall
    back to the stored values, so re-enabling with `{enabled: true}` works once
    a channel was previously chosen. Enabling the email channel requires an
    email on record (otherwise nothing could be delivered) → 422.
    """
    new_channel = body.channel if body.channel is not None else user.notify_channel
    if body.enabled and new_channel == "email" and not user.email:
        raise HTTPException(
            status_code=422,
            detail={"error": "email channel requires an email address on record"},
        )
    user.notify_enabled = body.enabled
    if body.channel is not None:
        user.notify_channel = body.channel
    if body.threshold is not None:
        user.notify_threshold = body.threshold
    await db.commit()
    await db.refresh(user)
    return NotifyOut(
        enabled=user.notify_enabled,
        channel=user.notify_channel,
        threshold=user.notify_threshold,
        deliverable=_deliverable(user),
    )


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

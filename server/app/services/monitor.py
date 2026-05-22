"""Wave 5.2 Monitor — daily cron + due-users + per-user dispatch."""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.run import RunCreate
from app.services.run_dispatcher import DuplicateRunningError, dispatch_run

logger = logging.getLogger(__name__)


WINDOW = timedelta(minutes=15)


async def find_due_users(
    db: AsyncSession,
    now_utc: datetime,
    window: timedelta = WINDOW,
) -> list[User]:
    """Return users whose briefing instant falls in (now-window, now] in their TZ."""
    candidates = (await db.execute(
        select(User).where(
            User.monitor_enabled.is_(True),
            User.briefing_time_local.is_not(None),
            User.briefing_tz.is_not(None),
        )
    )).scalars().all()

    due: list[User] = []
    for u in candidates:
        try:
            tz = ZoneInfo(u.briefing_tz)
        except Exception:
            continue
        local_now = now_utc.astimezone(tz)
        local_window_start = (now_utc - window).astimezone(tz)
        try:
            hh, mm = map(int, u.briefing_time_local.split(":"))
            briefing_today = local_now.replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
        except (ValueError, AttributeError):
            continue
        if local_window_start < briefing_today <= local_now:
            due.append(u)
    return due


async def dispatch_user_watchlist(
    db: AsyncSession,
    pool,
    user: User,
    now_utc: datetime,
) -> dict:
    """Dispatch every watchlist ticker for this user as a Run with triggered_by='monitor'."""
    items = (await db.execute(
        select(WatchlistItem.ticker).where(WatchlistItem.user_id == user.id)
    )).scalars().all()

    settings = get_settings()
    tz = ZoneInfo(user.briefing_tz)
    trade_date = now_utc.astimezone(tz).strftime("%Y-%m-%d")

    dispatched = 0
    skipped_dup = 0
    failed = 0
    for ticker in items:
        try:
            await dispatch_run(
                session=db,
                pool=pool,
                user_id=user.id,
                dashboard_dir=settings.dashboard_data_dir,
                body=RunCreate(ticker=ticker, trade_date=trade_date),
                triggered_by="monitor",
            )
            dispatched += 1
        except DuplicateRunningError:
            skipped_dup += 1
        except Exception:
            logger.exception(
                "monitor: dispatch failed for user=%s ticker=%s", user.id, ticker
            )
            failed += 1
    return {"dispatched": dispatched, "skipped_dup": skipped_dup, "failed": failed}


def compute_next_briefing_at(user: User, now_utc: datetime) -> datetime | None:
    """Returns the next UTC instant the user's briefing will fire, or None if disabled."""
    if not user.monitor_enabled or not user.briefing_time_local or not user.briefing_tz:
        return None
    try:
        tz = ZoneInfo(user.briefing_tz)
    except Exception:
        return None
    local_now = now_utc.astimezone(tz)
    try:
        hh, mm = map(int, user.briefing_time_local.split(":"))
    except (ValueError, AttributeError):
        return None
    briefing_today = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if briefing_today > local_now:
        return briefing_today.astimezone(timezone.utc)
    return (briefing_today + timedelta(days=1)).astimezone(timezone.utc)


# Cron entry (called by arq worker). Has to open its own session because
# cron contexts don't have a request-scoped db dep.
async def monitor_tick(ctx: dict) -> dict:
    """Fires every 15 min. Dispatches due users' watchlists.

    Opens its own session + arq pool — neither is provided by the cron context.
    Imports are function-scoped to avoid module-load cycles when the worker
    boots (services -> db -> models).
    """
    from app.db import get_session_factory  # avoid import cycle at module load
    from app.services.redis_pool import get_redis_pool  # worker-friendly pool helper
    factory = get_session_factory()
    pool = await get_redis_pool()
    now_utc = datetime.now(timezone.utc)
    results = []
    try:
        async with factory() as session:
            due = await find_due_users(session, now_utc)
            for user in due:
                r = await dispatch_user_watchlist(session, pool, user, now_utc)
                results.append({"user_id": str(user.id), **r})
    finally:
        await pool.close()
    if results:
        logger.info("monitor_tick: dispatched %d user(s): %s", len(results), results)
    return {"users_dispatched": len(results), "details": results}

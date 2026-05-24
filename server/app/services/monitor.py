"""Wave 5.2 Monitor — daily cron + due-users + per-user dispatch."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session_factory
from app.models.notification import MonitorBatch
from app.models.run import Run
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.run import RunCreate
from app.services.redis_pool import get_redis_pool
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
            # Pydantic validates briefing_tz at the API layer against
            # zoneinfo.available_timezones(), so an invalid value here
            # implies DB drift, a downgrade-then-upgrade with bad rows,
            # or a hand-rolled SQL fix. Log so it's debuggable instead
            # of a silent monitor outage.
            logger.warning(
                "monitor: skipping user=%s due to invalid briefing_tz=%r",
                u.id, u.briefing_tz,
            )
            continue
        local_now = now_utc.astimezone(tz)
        local_window_start = (now_utc - window).astimezone(tz)
        try:
            hh, mm = map(int, u.briefing_time_local.split(":"))
            briefing_today = local_now.replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
        except (ValueError, AttributeError):
            logger.warning(
                "monitor: skipping user=%s due to malformed briefing_time_local=%r",
                u.id, u.briefing_time_local,
            )
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

    # Wave 5.4 — record the batch for the notification sweep AFTER dispatch,
    # with expected_count = the number of monitor runs that ACTUALLY exist for
    # this (user, trade_date). Counting realized rows (not the optimistic
    # ticker count) is what lets the sweep know when the batch is provably
    # complete: a ticker that collided with a pre-existing manual run, or whose
    # dispatch raised before its row committed, produces no monitor row and so
    # must NOT be waited on — otherwise terminal_count could never reach an
    # over-optimistic expected_count and the digest would silently never fire.
    # Empty watchlist / all-failed-before-commit → no monitor runs → no batch,
    # nothing to notify. Re-dispatch on the same local day hits
    # UNIQUE(user_id, trade_date) and is ignored.
    monitor_run_count = (await db.execute(
        select(func.count())
        .select_from(Run)
        .where(
            Run.user_id == user.id,
            Run.trade_date == trade_date,
            Run.triggered_by == "monitor",
        )
    )).scalar_one()
    if monitor_run_count > 0:
        batch = MonitorBatch(
            id=uuid.uuid4(),
            user_id=user.id,
            trade_date=trade_date,
            expected_count=monitor_run_count,
        )
        db.add(batch)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()

    return {"dispatched": dispatched, "skipped_dup": skipped_dup, "failed": failed}


def compute_next_briefing_at(user: User, now_utc: datetime) -> datetime | None:
    """Returns the next UTC instant the user's briefing will fire, or None if disabled.

    Returning None for `monitor_enabled=False` or missing time/tz is a valid
    "not configured yet" state and does NOT log. Returning None because
    ZoneInfo() raised or the time string is malformed DOES log a warning —
    those are error states that should be debuggable.
    """
    if not user.monitor_enabled or not user.briefing_time_local or not user.briefing_tz:
        return None
    try:
        tz = ZoneInfo(user.briefing_tz)
    except Exception:
        logger.warning(
            "monitor: compute_next_briefing_at skipping user=%s — invalid briefing_tz=%r",
            user.id, user.briefing_tz,
        )
        return None
    local_now = now_utc.astimezone(tz)
    try:
        hh, mm = map(int, user.briefing_time_local.split(":"))
    except (ValueError, AttributeError):
        logger.warning(
            "monitor: compute_next_briefing_at skipping user=%s — malformed briefing_time_local=%r",
            user.id, user.briefing_time_local,
        )
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
    """
    factory = get_session_factory()
    pool = await get_redis_pool()
    now_utc = datetime.now(timezone.utc)
    results = []
    try:
        async with factory() as session:
            due = await find_due_users(session, now_utc)
            for user in due:
                # dispatch_user_watchlist catches per-ticker failures
                # internally; this outer wrap handles failures BEFORE the
                # per-ticker loop begins (e.g. transient DB error on the
                # watchlist SELECT). Without it, one user's failure would
                # silently skip every remaining user in the same tick.
                try:
                    r = await dispatch_user_watchlist(session, pool, user, now_utc)
                    results.append({"user_id": str(user.id), **r})
                except Exception:
                    logger.exception(
                        "monitor: dispatch failed for user=%s — continuing with next user",
                        user.id,
                    )
                    continue
    finally:
        await pool.close()
    if results:
        logger.info("monitor_tick: dispatched %d user(s): %s", len(results), results)
    return {"users_dispatched": len(results), "details": results}

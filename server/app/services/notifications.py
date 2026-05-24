"""Wave 5.4 — notification service + delivery sweep.

`should_notify` / `actionable_runs` encode the "quiet by default" rule: a batch
only earns a notification if at least one completed run carries an actionable
rating (per the user's threshold). Everything else is a quiet day.

`deliver_for_batch` is the claim-first idempotent delivery: it INSERTs a
`notifications` row under the UNIQUE(user_id, trade_date, channel) key as the
atomic claim. A conflict means the batch was already handled → no-op. A quiet
day still records a `skipped_no_signal` row so silence is auditable ("we
checked, nothing actionable") rather than an inferred absence.

`notification_sweep` is the arq cron that fires the deliveries. It only acts on
a batch once it is *provably* complete — `terminal_count == expected_count`,
read from the `monitor_batches` marker written at dispatch time. This is the
fix for the vacuous-true race: "zero non-terminal runs" is true before any run
exists, but `expected_count` is not satisfied until the whole batch lands.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session_factory
from app.models.notification import MonitorBatch, Notification, NotificationStatus
from app.models.run import Run, RunStatus
from app.models.user import User
from app.services.notification_channels import get_adapter

logger = logging.getLogger(__name__)


def parse_threshold(threshold: str) -> set[str]:
    """'BUY,SELL' → {'BUY','SELL'}. Empty/whitespace → empty set (notifies on nothing)."""
    return {p.strip() for p in (threshold or "").split(",") if p.strip()}


def actionable_runs(runs: list[Run], threshold: set[str]) -> list[Run]:
    """Succeeded runs whose final_rating is in the actionable threshold set."""
    return [
        r for r in runs
        if r.status == RunStatus.SUCCEEDED
        and r.final_rating is not None
        and r.final_rating in threshold
    ]


def should_notify(runs: list[Run], threshold: set[str]) -> bool:
    """True iff at least one run is actionable. The quiet-day invariant: an
    all-HOLD / all-None / all-FAILED batch returns False."""
    return len(actionable_runs(runs, threshold)) > 0


def build_digest(actionable: list[Run], base_url: str) -> dict:
    """One payload summarizing all actionable runs in the batch."""
    link = f"{base_url.rstrip('/')}/signals"
    n = len(actionable)
    head = [f"{r.final_rating} {r.ticker}" for r in actionable[:5]]
    summary = ", ".join(head)
    extra = n - len(head)
    if extra > 0:
        summary += f", +{extra} more"
    subject = f"{n} new trading signal{'s' if n != 1 else ''}: {summary}"
    lines = [f"- {r.final_rating} {r.ticker}" for r in actionable]
    text = (
        f"Your daily monitor found {n} actionable signal{'s' if n != 1 else ''}:\n"
        + "\n".join(lines)
        + f"\n\nView your full briefing: {link}"
    )
    return {"subject": subject, "text": text, "link": link, "count": n}


async def deliver_for_batch(
    db: AsyncSession,
    user: User,
    trade_date: str,
    terminal_runs: list[Run],
    settings,
) -> Notification | None:
    """Claim-first idempotent delivery for one completed (user, trade_date) batch.

    Returns the Notification row written, or None if the user opted out / the
    slot was already claimed by a prior tick. Send failures are caught and
    recorded as status='failed'; they never raise out of this function (the run
    pipeline must be unaffected).
    """
    if not user.notify_enabled or user.notify_channel == "none":
        return None  # opted out — do not pollute the audit table

    channel = user.notify_channel
    threshold = parse_threshold(user.notify_threshold)
    actionable = actionable_runs(terminal_runs, threshold)

    is_quiet = len(actionable) == 0
    notif = Notification(
        id=uuid.uuid4(),
        user_id=user.id,
        trade_date=trade_date,
        channel=channel,
        status=(
            NotificationStatus.SKIPPED_NO_SIGNAL.value
            if is_quiet
            else NotificationStatus.PENDING.value
        ),
    )
    # Claim the slot inside a SAVEPOINT so a UNIQUE(user,date,channel) conflict
    # rolls back only this INSERT — not the whole session transaction — and the
    # async greenlet context stays intact (a bare flush-then-rollback poisons
    # it). A conflict means another tick already owns this batch → no-op.
    try:
        async with db.begin_nested():
            db.add(notif)
            await db.flush()
    except IntegrityError:
        return None

    if is_quiet:
        await db.commit()  # record the quiet day, send nothing
        return notif

    # Actionable: build + send, then finalize status in the same transaction.
    digest = build_digest(actionable, settings.public_base_url)
    try:
        adapter = get_adapter(channel, settings)
        if adapter is None:
            notif.status = NotificationStatus.FAILED.value
            notif.error = f"no adapter for channel={channel}"
        else:
            await adapter.send(
                to=user.email or "",
                subject=digest["subject"],
                text=digest["text"],
            )
            notif.status = NotificationStatus.SENT.value
            notif.sent_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 — send failure must be non-fatal
        notif.status = NotificationStatus.FAILED.value
        notif.error = str(exc)[:512]
        logger.exception(
            "notification send failed user=%s date=%s channel=%s",
            user.id, trade_date, channel,
        )
    await db.commit()
    return notif


async def notification_sweep(ctx: dict) -> dict:
    """Cron: deliver digests for monitor batches that have provably completed.

    Offset from monitor_tick. Opens its own session. For each recent batch with
    no notification yet, fires only when every dispatched run is terminal
    (terminal_count == expected_count). Idempotent: a re-tick re-selects nothing
    because the prior delivery wrote a notification row.
    """
    factory = get_session_factory()
    settings = get_settings()
    # Bound the scan with a generous string-date window (trade_date is a stored
    # "YYYY-MM-DD" string — lexical compare, no naive/aware datetime trap).
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    async with factory() as session:
        batches = (await session.execute(
            select(MonitorBatch).where(MonitorBatch.trade_date >= cutoff_date)
        )).scalars().all()
        for b in batches:
            already = (await session.execute(
                select(Notification.id)
                .where(
                    Notification.user_id == b.user_id,
                    Notification.trade_date == b.trade_date,
                )
                .limit(1)
            )).first()
            if already is not None:
                continue

            user = (await session.execute(
                select(User).where(User.id == b.user_id)
            )).scalar_one_or_none()
            if user is None or not user.notify_enabled or user.notify_channel == "none":
                continue

            # Only ever notify for the user's CURRENT local day. This prevents
            # a retroactive blast: a user who flips notify on at 3pm must not be
            # paged about yesterday's (or older) batches that predate their
            # opt-in. briefing_tz is always set for any user who has batches
            # (the monitor requires it); guard defensively regardless.
            if not user.briefing_tz:
                continue
            try:
                local_today = datetime.now(timezone.utc).astimezone(
                    ZoneInfo(user.briefing_tz)
                ).strftime("%Y-%m-%d")
            except Exception:
                continue
            if b.trade_date != local_today:
                continue

            runs = (await session.execute(
                select(Run).where(
                    Run.user_id == b.user_id,
                    Run.trade_date == b.trade_date,
                    Run.triggered_by == "monitor",
                )
            )).scalars().all()
            terminal = [
                r for r in runs
                if r.status in (RunStatus.SUCCEEDED, RunStatus.FAILED)
            ]
            if len(terminal) < b.expected_count:
                continue  # batch not provably complete — try a later tick

            notif = await deliver_for_batch(session, user, b.trade_date, terminal, settings)
            if notif is None:
                continue
            if notif.status == NotificationStatus.SENT.value:
                sent += 1
            elif notif.status == NotificationStatus.SKIPPED_NO_SIGNAL.value:
                skipped += 1

    if sent or skipped:
        logger.info("notification_sweep: sent=%d skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped}

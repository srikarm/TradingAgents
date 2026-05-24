import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, false, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # github_id and google_sub are both nullable now that users can sign in
    # with either provider (or both, via auto-link-by-email). Unique partial
    # indexes are added in the alembic migration alongside this change.
    github_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Email is the canonical cross-provider identity. Unique partial index
    # added in the migration (WHERE email IS NOT NULL).
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Wave 5.2 — Monitor cron config. monitor_enabled gates the daily
    # briefing dispatch; briefing_time_local + briefing_tz together
    # specify the user's preferred firing instant (HH:MM in IANA tz).
    monitor_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    briefing_time_local: Mapped[str | None] = mapped_column(
        String(5), nullable=True
    )
    briefing_tz: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Wave 5.4 — Notification opt-in. notify_enabled gates out-of-band
    # delivery; notify_channel selects the adapter ('none'|'email'|'webpush');
    # notify_threshold is the comma-separated set of ratings that count as
    # actionable (anything else is a "quiet day" and never sends).
    notify_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    notify_channel: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="none"
    )
    notify_threshold: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="BUY,SELL"
    )


async def find_or_create_by_identity(
    db: AsyncSession,
    *,
    email: str | None,
    github_id: str | None = None,
    google_sub: str | None = None,
) -> User:
    """
    Resolve a user by verified-email-as-canonical-identity, with legacy
    fallback to provider-id lookup.

    Order:
      1. If email provided and matches an existing user, return that user
         and backfill any missing provider ids.
      2. Else if github_id provided and matches an existing user, return
         that user and backfill email if missing.
      3. Else if google_sub provided and matches an existing user, return
         that user and backfill email if missing.
      4. Else create a new user with whatever fields are provided.

    On race-condition IntegrityError during step 4, re-run the lookup
    chain — another concurrent request likely created the user.
    """
    # 1. Lookup by email (canonical)
    if email:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is not None:
            if github_id and user.github_id is None:
                user.github_id = github_id
            if google_sub and user.google_sub is None:
                user.google_sub = google_sub
            return user

    # 2. Legacy fallback: lookup by github_id
    if github_id:
        user = (
            await db.execute(select(User).where(User.github_id == github_id))
        ).scalar_one_or_none()
        if user is not None:
            if email and user.email is None:
                user.email = email
            if google_sub and user.google_sub is None:
                user.google_sub = google_sub
            return user

    # 3. Legacy fallback: lookup by google_sub
    if google_sub:
        user = (
            await db.execute(select(User).where(User.google_sub == google_sub))
        ).scalar_one_or_none()
        if user is not None:
            if email and user.email is None:
                user.email = email
            if github_id and user.github_id is None:
                user.github_id = github_id
            return user

    # 4. New user
    user = User(
        id=uuid.uuid4(),
        email=email,
        github_id=github_id,
        google_sub=google_sub,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Race: another request just inserted a user with the same identity.
        # Roll back and re-resolve. The retry MUST succeed since the
        # unique-index conflict means a matching row now exists.
        await db.rollback()
        if email:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one()
            return user
        if github_id:
            user = (
                await db.execute(select(User).where(User.github_id == github_id))
            ).scalar_one()
            return user
        user = (
            await db.execute(select(User).where(User.google_sub == google_sub))
        ).scalar_one()
        return user

    return user

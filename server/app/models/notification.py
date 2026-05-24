"""Wave 5.4 — notification delivery + monitor-batch tracking.

Two tables:

- ``monitor_batches`` records, at monitor_tick dispatch time, how many
  watchlist tickers were dispatched for a (user, trade_date). The notification
  sweep uses ``expected_count`` to know when the batch is *provably* complete
  (terminal_count == expected_count) rather than inferring completeness from
  "zero non-terminal runs", which is vacuously true before any run exists.

- ``notifications`` is the delivery ledger. UNIQUE(user_id, trade_date,
  channel) is both the idempotency key (claim-first insert) and the audit
  record — a ``skipped_no_signal`` row makes a quiet day auditable so silence
  is trustworthy ("we checked, nothing actionable") rather than an inferred
  absence.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"          # claimed, not yet sent
    SENT = "sent"                # delivered to the channel adapter successfully
    FAILED = "failed"            # send attempted, adapter raised (non-fatal)
    SKIPPED_NO_SIGNAL = "skipped_no_signal"  # batch complete, nothing actionable


class MonitorBatch(Base):
    __tablename__ = "monitor_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # User-tz "YYYY-MM-DD" string — the SAME value the Run rows carry, so the
    # sweep keys off a stored string and never recomputes "today" (which would
    # reintroduce the naive/aware datetime-dialect trap at a midnight boundary).
    trade_date: Mapped[str] = mapped_column(String(10))
    expected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "trade_date", name="uq_monitor_batch_user_date"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    trade_date: Mapped[str] = mapped_column(String(10))
    channel: Mapped[str] = mapped_column(String(16))
    # Stored as the enum's string value; kept as a plain String column (not a
    # DB enum) to avoid the Alembic enum-drop-on-downgrade hazard this project
    # was bitten by in Wave 3.
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "trade_date", "channel", name="uq_notification_user_date_channel"
        ),
    )

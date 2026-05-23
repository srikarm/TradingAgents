import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), index=True
    )
    final_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    results_path: Mapped[str] = mapped_column(String(1024))
    error_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(nullable=True)  # TEXT
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Wave 5.2 — Provenance of the dispatch. 'manual' = POST /runs;
    # 'monitor' = monitor_tick cron. server_default backfills existing rows.
    triggered_by: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="manual"
    )

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MemoryEntryStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ticker", "trade_date", name="uq_memory_entry_user_ticker_date"
        ),
        CheckConstraint(
            "status != 'RESOLVED' OR raw_return IS NOT NULL",
            name="ck_memory_entry_resolved_has_raw_return",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    rating: Mapped[str] = mapped_column(String(16))
    status: Mapped[MemoryEntryStatus] = mapped_column(
        Enum(MemoryEntryStatus, name="memory_entry_status"), index=True
    )
    raw_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_text: Mapped[str | None] = mapped_column(nullable=True)
    reflection_text: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

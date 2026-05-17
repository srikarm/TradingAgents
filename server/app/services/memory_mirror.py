"""One-way sync: disk `trading_memory.md` → Postgres `memory_entries`.

Reuses `TradingMemoryLog.load_entries()` from the root package as the parser
so we never get two implementations of the markdown format. The disk path is
constructed via `user_root` — never trust a route-supplied path here.

Per spec §4.4: disk remains the source of truth. The mirror is a cache for
fast portfolio queries. Hand-edits to the markdown log are picked up on the
next sync (worker post-run, or fallback per-request from the portfolio router).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.services.user_root import user_results_dir


def _pct_to_float(s: str | None) -> float | None:
    """Convert "+2.3%" → 0.023; "-1.5%" → -0.015; "n/a" / None / bad → None."""
    if s is None:
        return None
    s = s.strip()
    if not s or s.lower() == "n/a":
        return None
    if not s.endswith("%"):
        return None
    try:
        return float(s[:-1]) / 100.0
    except ValueError:
        return None


def _holding_to_int(s: str | None) -> int | None:
    """Convert "7d" → 7; "n/a" / None / bad → None."""
    if not s:
        return None
    s = s.strip()
    if s.lower() == "n/a":
        return None
    if s.endswith("d"):
        s = s[:-1]
    try:
        return int(s)
    except ValueError:
        return None


def _memory_log_path(dashboard_dir: Path, user_id: uuid.UUID) -> Path:
    return user_results_dir(dashboard_dir, str(user_id)) / "memory" / "trading_memory.md"


def _parse_disk(path: Path) -> list[dict]:
    """Return the list of entry dicts parsed from disk, or [] if file absent."""
    if not path.is_file():
        return []
    from tradingagents.agents.utils.memory import TradingMemoryLog

    log = TradingMemoryLog({"memory_log_path": str(path)})
    return log.load_entries()


async def sync_user(
    session: AsyncSession,
    *,
    dashboard_dir: Path,
    user_id: uuid.UUID,
) -> int:
    """Upsert every entry from the user's disk log into memory_entries.

    Returns the number of entries processed (inserted + updated, ignoring
    malformed entries the parser already skipped).
    """
    path = _memory_log_path(dashboard_dir, user_id)
    parsed = _parse_disk(path)
    if not parsed:
        return 0

    now = datetime.now(timezone.utc)
    processed = 0

    for entry in parsed:
        ticker = entry.get("ticker")
        trade_date = entry.get("date")
        rating = entry.get("rating")
        if not (ticker and trade_date and rating):
            continue

        existing = (
            await session.execute(
                select(MemoryEntry).where(
                    MemoryEntry.user_id == user_id,
                    MemoryEntry.ticker == ticker,
                    MemoryEntry.trade_date == trade_date,
                )
            )
        ).scalar_one_or_none()

        status = MemoryEntryStatus.PENDING if entry.get("pending") else MemoryEntryStatus.RESOLVED
        raw = _pct_to_float(entry.get("raw"))
        alpha = _pct_to_float(entry.get("alpha"))
        holding = _holding_to_int(entry.get("holding"))
        decision = entry.get("decision") or None
        reflection = entry.get("reflection") or None

        if existing is None:
            session.add(
                MemoryEntry(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    ticker=ticker,
                    trade_date=trade_date,
                    rating=rating,
                    status=status,
                    raw_return=raw,
                    alpha_return=alpha,
                    holding_days=holding,
                    decision_text=decision,
                    reflection_text=reflection,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            existing.rating = rating
            existing.status = status
            existing.raw_return = raw
            existing.alpha_return = alpha
            existing.holding_days = holding
            existing.decision_text = decision
            existing.reflection_text = reflection
            existing.updated_at = now
        processed += 1

    await session.commit()
    return processed

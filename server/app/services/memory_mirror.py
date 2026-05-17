"""One-way sync: disk `trading_memory.md` → Postgres `memory_entries`.

Reuses `TradingMemoryLog.load_entries()` from the root package as the parser
so we never get two implementations of the markdown format. The disk path is
constructed via `user_root` — never trust a route-supplied path here.

Per spec §4.4: disk remains the source of truth. The mirror is a cache for
fast portfolio queries. Hand-edits to the markdown log are picked up on the
next sync (worker post-run, or fallback per-request from the portfolio router).
"""

from __future__ import annotations

import hashlib
import logging
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_entry import MemoryEntry, MemoryEntryStatus
from app.services.user_root import user_results_dir

logger = logging.getLogger(__name__)

# Postgres advisory-lock namespace for memory_mirror.sync_user races.
# Two-key form: (NAMESPACE, signed_int32_from_user_uuid). Greppable in
# pg_locks as classid=0x4D4D5252 ("MMRR"). See spec §3.
_LOCK_NAMESPACE = 0x4D4D5252


def _user_key(user_id: uuid.UUID) -> int:
    """Map a user UUID to a signed int32 advisory-lock key (deterministic)."""
    # Python's built-in hash() is randomized per-process; BLAKE2 is
    # deterministic — required so two workers compute the same key.
    # Collision probability ≈ 1/2³² per user pair; cost of collision is
    # a spurious skip, not a correctness bug. Accepted per spec §3.2.
    digest = hashlib.blake2b(user_id.bytes, digest_size=4).digest()
    return struct.unpack(">i", digest)[0]


async def _try_acquire(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Try to acquire the per-user advisory lock for this transaction.

    Returns True on Postgres if the lock is acquired (or always True on
    non-Postgres dialects — the lock is a no-op for SQLite test runs).
    The lock auto-releases on COMMIT / ROLLBACK.
    """
    bind = getattr(session, "bind", None)
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name != "postgresql":
        return True
    # CAST(... AS integer) pins the (int4, int4) overload of
    # pg_try_advisory_xact_lock without colliding with SQLAlchemy text()'s
    # ":bind" syntax (the Postgres "::" cast operator conflicts with it).
    row = await session.execute(
        text(
            "SELECT pg_try_advisory_xact_lock("
            "CAST(:ns AS integer), CAST(:uid AS integer))"
        ),
        {"ns": _LOCK_NAMESPACE, "uid": _user_key(user_id)},
    )
    return bool(row.scalar())


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
    malformed entries the parser already skipped). Returns 0 if another
    caller holds the per-user advisory lock — the in-flight sync will
    cover the work; this caller no-ops with a warning. See spec §6.

    Concurrency contract is exercised by tests/test_memory_mirror_
    concurrent_pg.py — run `cd server && uv run pytest -m pg` before
    opening a PR that touches this file.
    """
    if not await _try_acquire(session, user_id):
        logger.warning(
            "memory_mirror sync skipped for user_id=%s — lock held by another sync",
            user_id,
        )
        return 0

    path = _memory_log_path(dashboard_dir, user_id)
    parsed = _parse_disk(path)
    if not parsed:
        return 0

    now = datetime.now(timezone.utc)
    processed = 0
    skipped = 0

    for entry in parsed:
        ticker = entry.get("ticker")
        trade_date = entry.get("date")
        rating = entry.get("rating")
        if not (ticker and trade_date and rating):
            skipped += 1
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
    if skipped:
        logger.warning(
            "memory_mirror: skipped %d of %d entries (missing ticker/date/rating)"
            " for user_id=%s",
            skipped, len(parsed), user_id,
        )
    return processed

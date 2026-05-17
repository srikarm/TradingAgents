"""Pure portfolio arithmetic.

All functions accept a list of entry dicts with at least the keys:
    ticker, trade_date (YYYY-MM-DD str), rating, status,
    raw_return (float|None), alpha_return (float|None), holding_days (int|None),
    created_at (str or datetime — only used for tie-breaking on same trade_date)

Functions are pure — no DB, no I/O, no time. The rating→size mapping is the
single source of truth for position sign and magnitude in v1.

Per spec §5.3 caveat 1: Sharpe is computed per-decision (not daily MTM) and
is NOT annualized. This is an explicit v1 simplification; a daily MTM version
is a v2 concern.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

RATING_TO_SIZE: dict[str, float] = {
    "Buy": 1.0,
    "Overweight": 0.5,
    "Hold": 0.0,
    "Underweight": -0.5,
    "Sell": -1.0,
}


def rating_to_size(rating: str | None) -> float:
    """Map a rating string to a position size. Unknown → 0.0 (defensive)."""
    if not rating:
        return 0.0
    return RATING_TO_SIZE.get(rating, 0.0)


def _resolved_pnls(entries: Iterable[dict[str, Any]]) -> list[tuple[str, str, float]]:
    """Return list of (trade_date, created_at_sort_key, pnl) for resolved entries.

    Skips pending entries. Resolved entries always have raw_return set
    (enforced by ck_memory_entry_resolved_has_raw_return — spec §4).
    A None raw_return on a status='resolved' entry is a contract violation
    and will surface as a TypeError on the size*float(r) below — desirable
    loud-failure behavior, not a regression.
    """
    out: list[tuple[str, str, float]] = []
    for e in entries:
        if e.get("status") != "resolved":
            continue
        r = e.get("raw_return")
        size = rating_to_size(e.get("rating"))
        sort_key = str(e.get("created_at") or e.get("trade_date") or "")
        out.append((str(e["trade_date"]), sort_key, size * float(r)))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def cumulative_curve(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the prefix-sum cumulative P&L points, ordered by date."""
    points: list[dict[str, Any]] = []
    running = 0.0
    for trade_date, _sort, pnl in _resolved_pnls(entries):
        running += pnl
        points.append({"trade_date": trade_date, "cumulative_pnl": running})
    return points


def win_rate(entries: Iterable[dict[str, Any]]) -> float:
    pnls = [p for _, _, p in _resolved_pnls(entries)]
    if not pnls:
        return 0.0
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)


def sharpe_ratio(entries: Iterable[dict[str, Any]]) -> float:
    """Per-decision Sharpe (NOT annualized — spec §5.3 caveat 1)."""
    pnls = [p for _, _, p in _resolved_pnls(entries)]
    if len(pnls) < 2:
        return 0.0
    std = statistics.pstdev(pnls)
    if std == 0:
        return 0.0
    return statistics.fmean(pnls) / std


def max_drawdown(entries: Iterable[dict[str, Any]]) -> float:
    """Return the most negative (cumulative - running_max). Always <= 0.

    Peak is initialized to 0.0 (capital-deployed baseline) so a losing first
    trade counts as a drawdown from zero. Initializing peak to pts[0] would
    silently report 0% drawdown when the first trade went immediately negative.
    """
    pts = cumulative_curve(entries)
    if not pts:
        return 0.0
    peak = 0.0
    dd = 0.0
    for p in pts:
        if p["cumulative_pnl"] > peak:
            peak = p["cumulative_pnl"]
        gap = p["cumulative_pnl"] - peak
        if gap < dd:
            dd = gap
    return dd


def summary(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries_list = list(entries)
    pts = cumulative_curve(entries_list)
    return {
        "trade_count": len(_resolved_pnls(entries_list)),
        "win_rate": win_rate(entries_list),
        "sharpe": sharpe_ratio(entries_list),
        "max_drawdown": max_drawdown(entries_list),
        "cumulative_pnl": pts[-1]["cumulative_pnl"] if pts else 0.0,
    }

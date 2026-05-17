import math

import pytest

from app.services.portfolio_calc import (
    RATING_TO_SIZE,
    cumulative_curve,
    max_drawdown,
    rating_to_size,
    sharpe_ratio,
    summary,
    win_rate,
)


def _entry(trade_date, rating, raw_return, status="resolved", created_at=None):
    return {
        "ticker": "X",
        "trade_date": trade_date,
        "rating": rating,
        "status": status,
        "raw_return": raw_return,
        "alpha_return": None,
        "holding_days": None,
        "created_at": created_at or trade_date,
    }


@pytest.mark.parametrize("rating, expected", [
    ("Buy", 1.0), ("Overweight", 0.5), ("Hold", 0.0),
    ("Underweight", -0.5), ("Sell", -1.0),
    ("buy", 0.0),
    ("", 0.0), ("Garbage", 0.0),
])
def test_rating_to_size(rating, expected):
    assert rating_to_size(rating) == expected
    assert RATING_TO_SIZE.get("Buy") == 1.0


def test_cumulative_curve_orders_by_date_then_created_at():
    entries = [
        _entry("2024-05-10", "Buy", 0.02, created_at="2024-05-10T10:00"),
        _entry("2024-05-09", "Sell", -0.01, created_at="2024-05-09T10:00"),
        _entry("2024-05-10", "Hold", 0.0, created_at="2024-05-10T09:00"),
    ]
    pts = cumulative_curve(entries)
    assert [p["trade_date"] for p in pts] == ["2024-05-09", "2024-05-10", "2024-05-10"]
    assert pts[-1]["cumulative_pnl"] == pytest.approx(0.03)


def test_cumulative_curve_skips_pending_and_null_returns():
    entries = [
        _entry("2024-05-10", "Buy", 0.02),
        _entry("2024-05-11", "Buy", None, status="resolved"),
        _entry("2024-05-12", "Buy", 0.01, status="pending"),
    ]
    pts = cumulative_curve(entries)
    assert len(pts) == 1
    assert pts[0]["cumulative_pnl"] == pytest.approx(0.02)


def test_win_rate_basic():
    entries = [
        _entry("2024-05-10", "Buy", 0.02),
        _entry("2024-05-11", "Sell", 0.01),
        _entry("2024-05-12", "Buy", -0.01),
    ]
    assert win_rate(entries) == pytest.approx(1 / 3)


def test_win_rate_empty_is_zero():
    assert win_rate([]) == 0.0


def test_sharpe_zero_for_constant_returns():
    entries = [_entry(f"2024-05-{i:02d}", "Buy", 0.01) for i in range(10, 15)]
    assert sharpe_ratio(entries) == 0.0


def test_sharpe_positive_for_winners():
    entries = [
        _entry("2024-05-10", "Buy", 0.02),
        _entry("2024-05-11", "Buy", 0.01),
        _entry("2024-05-12", "Buy", 0.03),
    ]
    s = sharpe_ratio(entries)
    assert s > 0
    assert math.isfinite(s)


def test_max_drawdown_simple():
    entries = [
        _entry("2024-05-10", "Buy", 0.02),
        _entry("2024-05-11", "Buy", -0.01),
        _entry("2024-05-12", "Buy", 0.02),
    ]
    assert max_drawdown(entries) == pytest.approx(-0.01)


def test_max_drawdown_all_positive_is_zero():
    entries = [
        _entry("2024-05-10", "Buy", 0.01),
        _entry("2024-05-11", "Buy", 0.02),
    ]
    assert max_drawdown(entries) == 0.0


def test_max_drawdown_empty_is_zero():
    assert max_drawdown([]) == 0.0


def test_max_drawdown_first_trade_is_loser():
    """Regression: if the very first trade loses money, peak starts at 0.0
    (not at pts[0]), so the loss counts. Previously a losing-first-trade
    portfolio would silently report 0% drawdown."""
    entries = [
        _entry("2024-05-10", "Buy", -0.05),  # cumulative starts at -0.05
        _entry("2024-05-11", "Buy", 0.02),   # cumulative climbs to -0.03
    ]
    assert max_drawdown(entries) == pytest.approx(-0.05)


def test_summary_aggregates_all_metrics():
    entries = [
        _entry("2024-05-10", "Buy", 0.02),
        _entry("2024-05-11", "Sell", 0.01),
        _entry("2024-05-12", "Buy", 0.03),
    ]
    s = summary(entries)
    assert s["trade_count"] == 3
    assert s["cumulative_pnl"] == pytest.approx(0.04)
    assert s["win_rate"] == pytest.approx(2 / 3)
    assert s["max_drawdown"] == pytest.approx(-0.01)


def test_summary_empty():
    s = summary([])
    assert s == {
        "trade_count": 0,
        "win_rate": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "cumulative_pnl": 0.0,
    }

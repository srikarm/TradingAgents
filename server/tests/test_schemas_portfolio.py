import pytest
from pydantic import ValidationError

from app.models.memory_entry import MemoryEntryStatus
from app.schemas.portfolio import (
    DecisionPin,
    MemoryEntryOut,
    PnLPoint,
    PortfolioCurveOut,
    PortfolioSummaryOut,
    PricePoint,
    TickerDetailOut,
)


def test_memory_entry_out_accepts_resolved():
    e = MemoryEntryOut(
        ticker="NVDA",
        trade_date="2024-05-10",
        rating="Buy",
        status="resolved",
        raw_return=0.023,
        alpha_return=0.011,
        holding_days=7,
    )
    assert e.status == "resolved"
    assert e.raw_return == pytest.approx(0.023)


def test_memory_entry_out_accepts_pending_with_nulls():
    e = MemoryEntryOut(
        ticker="NVDA", trade_date="2024-05-10", rating="Buy", status="pending",
        raw_return=None, alpha_return=None, holding_days=None,
    )
    assert e.status == "pending"
    assert e.raw_return is None  # invariant: pending ⟹ raw_return is None


def test_portfolio_summary_shape():
    s = PortfolioSummaryOut(
        trade_count=3,
        win_rate=0.667,
        sharpe=1.23,
        max_drawdown=-0.05,
        cumulative_pnl=0.04,
    )
    assert s.trade_count == 3
    assert s.win_rate == pytest.approx(0.667)


def test_portfolio_curve_shape():
    c = PortfolioCurveOut(
        points=[
            PnLPoint(trade_date="2024-05-10", cumulative_pnl=0.02),
            PnLPoint(trade_date="2024-05-11", cumulative_pnl=0.04),
        ]
    )
    assert len(c.points) == 2
    assert c.points[1].cumulative_pnl == pytest.approx(0.04)


def test_ticker_detail_shape():
    d = TickerDetailOut(
        ticker="NVDA",
        prices=[PricePoint(trade_date="2024-05-10", close=950.12)],
        decisions=[
            DecisionPin(
                trade_date="2024-05-10",
                rating="Buy",
                status="resolved",
                raw_return=0.023,
            )
        ],
    )
    assert d.ticker == "NVDA"
    assert d.prices[0].close == pytest.approx(950.12)
    assert d.decisions[0].rating == "Buy"


def test_decision_pin_rejects_pending_with_raw_return():
    """Spec §3: status='pending' requires raw_return=None."""
    with pytest.raises(ValidationError):
        DecisionPin(
            trade_date="2024-05-10",
            rating="Buy",
            status="pending",
            raw_return=0.5,
        )


def test_decision_pin_accepts_pending_with_null_raw():
    """The valid pending case (status='pending', raw_return=None) must pass."""
    pin = DecisionPin(
        trade_date="2024-05-10",
        rating="Buy",
        status="pending",
        raw_return=None,
    )
    assert pin.status == "pending"
    assert pin.raw_return is None


def test_memory_entry_out_rejects_pending_with_raw_return():
    """Spec §3 mirrored on MemoryEntryOut."""
    with pytest.raises(ValidationError):
        MemoryEntryOut(
            ticker="NVDA",
            trade_date="2024-05-10",
            rating="Buy",
            status="pending",
            raw_return=0.5,
            alpha_return=None,
            holding_days=None,
        )


def test_decision_pin_rejects_pending_with_zero_raw_return():
    """Pin the boundary case: raw_return=0.0 is `not None`, so the validator
    rejects it even though 0.0 is a valid resolved return. Pending means
    'no measurement yet' — 0.0 is a measurement of zero, not the absence
    of one. Guards against a future refactor that loosens the check from
    `is not None` to something like `> 0`."""
    with pytest.raises(ValidationError):
        DecisionPin(
            trade_date="2024-05-10",
            rating="Buy",
            status="pending",
            raw_return=0.0,
        )


def test_memory_entry_out_accepts_enum_input():
    """Both string ("pending") and MemoryEntryStatus enum member inputs
    must work after v3+ #4 swaps the field type. Guards against a future
    Pydantic config regression that breaks enum-typed field validation.
    """
    e = MemoryEntryOut(
        ticker="NVDA",
        trade_date="2024-05-10",
        rating="Buy",
        status=MemoryEntryStatus.RESOLVED,
        raw_return=0.023,
        alpha_return=0.011,
        holding_days=7,
    )
    assert e.status == "resolved"  # str-enum equality
    assert e.status is MemoryEntryStatus.RESOLVED

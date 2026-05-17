from datetime import datetime, timezone

import pytest

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

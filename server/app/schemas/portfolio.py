from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

MemoryEntryStatusLiteral = Literal["pending", "resolved"]


class MemoryEntryOut(BaseModel):
    ticker: str
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None
    alpha_return: float | None
    holding_days: int | None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _pending_requires_null_raw(self) -> "MemoryEntryOut":
        if self.status == "pending" and self.raw_return is not None:
            raise ValueError(
                f"MemoryEntryOut invariant violated: status='pending' requires "
                f"raw_return=None, got {self.raw_return!r}"
            )
        return self


class PnLPoint(BaseModel):
    trade_date: str
    cumulative_pnl: float


class PortfolioSummaryOut(BaseModel):
    trade_count: int
    win_rate: float
    sharpe: float
    max_drawdown: float
    # Sum of per-decision P&L (same units as PnLPoint.cumulative_pnl);
    # not annualized; not a return percentage despite how the UI renders it.
    cumulative_pnl: float


class PortfolioCurveOut(BaseModel):
    points: list[PnLPoint]


class PricePoint(BaseModel):
    trade_date: str
    close: float


class DecisionPin(BaseModel):
    trade_date: str
    rating: str
    status: MemoryEntryStatusLiteral
    raw_return: float | None

    @model_validator(mode="after")
    def _pending_requires_null_raw(self) -> "DecisionPin":
        if self.status == "pending" and self.raw_return is not None:
            raise ValueError(
                f"DecisionPin invariant violated: status='pending' requires "
                f"raw_return=None, got {self.raw_return!r}"
            )
        return self


class TickerDetailOut(BaseModel):
    ticker: str
    prices: list[PricePoint]
    decisions: list[DecisionPin]

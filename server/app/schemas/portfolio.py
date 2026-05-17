from typing import Literal

from pydantic import BaseModel, ConfigDict

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


class PnLPoint(BaseModel):
    trade_date: str
    cumulative_pnl: float


class PortfolioSummaryOut(BaseModel):
    trade_count: int
    win_rate: float
    sharpe: float
    max_drawdown: float
    cumulative_return: float


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


class TickerDetailOut(BaseModel):
    ticker: str
    prices: list[PricePoint]
    decisions: list[DecisionPin]

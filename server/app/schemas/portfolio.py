from pydantic import BaseModel, ConfigDict, model_validator

# Status values live in app.models.memory_entry.MemoryEntryStatus — the enum
# is the single source of truth. Schemas-importing-from-models is acceptable
# here because MemoryEntryStatus is a str-Enum (pure data type) with no
# SQLAlchemy / DB dependencies; no circular-import risk.
# If a new status is ever added, update only MemoryEntryStatus — do NOT
# re-introduce a `MemoryEntryStatusLiteral = Literal[...]` alias here.
from app.models.memory_entry import MemoryEntryStatus


class MemoryEntryOut(BaseModel):
    ticker: str
    trade_date: str
    rating: str
    status: MemoryEntryStatus
    raw_return: float | None
    alpha_return: float | None
    holding_days: int | None

    model_config = ConfigDict(from_attributes=True)

    # NOTE: The _pending_requires_null_raw validator below is intentionally
    # duplicated on DecisionPin rather than extracted into a shared mixin.
    # Two short identical methods are clearer than the indirection. If a
    # third schema ever needs the same invariant, extract then. (Spec §4.2.)
    @model_validator(mode="after")
    def _pending_requires_null_raw(self) -> "MemoryEntryOut":
        # PENDING means the prediction window hasn't closed yet — a realized
        # raw_return is logically impossible. `return self` is required by
        # Pydantic's mode='after' contract.
        if self.status == "pending" and self.raw_return is not None:
            raise ValueError(
                f"MemoryEntryOut invariant violated: status='pending' requires "
                f"raw_return=None, got raw_return={self.raw_return!r} "
                f"ticker={self.ticker!r} trade_date={self.trade_date!r} "
                f"rating={self.rating!r}"
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


class OHLCVBar(BaseModel):
    """One bar of OHLCV market data.

    `trade_date` is ISO date "YYYY-MM-DD" for daily (interval=1d)
    or ISO datetime UTC "YYYY-MM-DDTHH:MM:SSZ" for hourly (interval=1h).
    The client decodes accordingly.
    """
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class DecisionPin(BaseModel):
    # No `model_config = ConfigDict(from_attributes=True)` here: DecisionPin
    # is constructed from explicit kwargs in `routers/portfolio.py` (around
    # line 138), NOT via `model_validate(orm_row)`. Adding from_attributes
    # later would also work, but switching to model_validate without it
    # would silently fail with a ValidationError.
    trade_date: str
    rating: str
    status: MemoryEntryStatus
    raw_return: float | None

    @model_validator(mode="after")
    def _pending_requires_null_raw(self) -> "DecisionPin":
        # See MemoryEntryOut for the duplication rationale (spec §4.2).
        # PENDING means the prediction window hasn't closed; raw_return
        # is logically impossible until the trade resolves.
        if self.status == "pending" and self.raw_return is not None:
            raise ValueError(
                f"DecisionPin invariant violated: status='pending' requires "
                f"raw_return=None, got raw_return={self.raw_return!r} "
                f"trade_date={self.trade_date!r} rating={self.rating!r}"
            )
        return self


class TickerDetailOut(BaseModel):
    ticker: str
    prices: list[OHLCVBar]
    decisions: list[DecisionPin]
    data_range_clipped: bool = False  # True when hourly request was clipped to 60 days

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AnalystKey = Literal["market", "social", "news", "fundamentals"]
AssetType = Literal["stock", "crypto"]
RunStatusLiteral = Literal["queued", "running", "succeeded", "failed"]


class RunOut(BaseModel):
    id: uuid.UUID
    ticker: str
    trade_date: str
    status: str
    final_rating: str | None
    created_at: datetime
    completed_at: datetime | None
    triggered_by: str  # Wave 5.2; 'manual' (default) or 'monitor'

    model_config = ConfigDict(from_attributes=True)


class RunListOut(BaseModel):
    items: list[RunOut]


class ReportSections(BaseModel):
    market: str | None = None
    sentiment: str | None = None
    news: str | None = None
    fundamentals: str | None = None
    investment_plan: str | None = None
    trader_plan: str | None = None
    final: str | None = None


class RunDetailOut(RunOut):
    results_path: str
    error_summary: str | None
    report_sections: ReportSections


class RunCreate(BaseModel):
    """Request body for POST /runs."""

    ticker: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9.\-]+$")
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    analysts: list[AnalystKey] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"],
        max_length=4,
    )
    asset_type: AssetType = "stock"


class RunTailOut(BaseModel):
    """Response from GET /runs/{id}/tail."""

    content: str
    next_offset: int
    status: RunStatusLiteral

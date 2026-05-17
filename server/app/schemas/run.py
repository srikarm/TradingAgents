import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RunOut(BaseModel):
    id: uuid.UUID
    ticker: str
    trade_date: str
    status: str
    final_rating: str | None
    created_at: datetime
    completed_at: datetime | None

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

    ticker: str = Field(min_length=1, max_length=12)
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"],
        max_length=4,
    )
    llm_provider: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None
    asset_type: str = "stock"


class RunTailOut(BaseModel):
    """Response from GET /runs/{id}/tail."""

    content: str
    next_offset: int
    status: str

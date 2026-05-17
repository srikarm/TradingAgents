import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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

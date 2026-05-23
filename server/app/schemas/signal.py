from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SignalOut(BaseModel):
    run_id: UUID
    ticker: str
    trade_date: str
    status: str
    final_rating: str | None
    created_at: datetime
    completed_at: datetime | None
    notes: str | None

    model_config = ConfigDict(from_attributes=False)


class SignalListOut(BaseModel):
    items: list[SignalOut]
    trade_date: str | None

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WatchlistItemOut(BaseModel):
    id: UUID
    ticker: str
    notes: str | None
    added_at: datetime

    model_config = {"from_attributes": True}


class WatchlistAdd(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=500)


class WatchlistNotesUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=500)

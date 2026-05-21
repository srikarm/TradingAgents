from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WatchlistItemOut(BaseModel):
    id: UUID
    ticker: str
    notes: str | None
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistAdd(BaseModel):
    # Ticker pattern mirrors app.services.user_root.TICKER_RE — uppercase
    # alnum + . / - , 1-12 chars. Enforced here (Pydantic returns 422 on
    # mismatch) so the router doesn't need a redundant manual check.
    ticker: str = Field(..., pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$")
    notes: str | None = Field(default=None, max_length=500)


class WatchlistNotesUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=500)

from datetime import datetime
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator


_VALID_TZ = available_timezones()


class MonitorUpdate(BaseModel):
    enabled: bool
    briefing_time_local: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    briefing_tz: str | None = None

    @field_validator("briefing_tz")
    @classmethod
    def _validate_tz(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_TZ:
            raise ValueError(f"unknown timezone: {v}")
        return v


class MonitorOut(BaseModel):
    enabled: bool
    briefing_time_local: str | None
    briefing_tz: str | None
    next_briefing_at: datetime | None

    model_config = ConfigDict(from_attributes=False)

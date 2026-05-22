import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    id: uuid.UUID
    # Relaxed to Optional in Wave 5.2 — User.github_id is Mapped[str | None]
    # (both github and google are nullable since the dual-provider change).
    github_id: str | None
    email: str | None
    created_at: datetime
    # Wave 5.2 — Monitor config surfaced on /me so the web UI can render the
    # MonitorSection without an extra round-trip.
    monitor_enabled: bool
    briefing_time_local: str | None
    briefing_tz: str | None

    model_config = ConfigDict(from_attributes=True)

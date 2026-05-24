from pydantic import BaseModel, ConfigDict, field_validator

# Channels the prefs endpoint will accept. 'none' = opted out at the channel
# level even if notify_enabled flips true. 'webpush' is reserved for a future
# additive channel (the adapter seam exists; live delivery is email-only in v1).
_VALID_CHANNELS = {"none", "email", "webpush"}


class NotifyUpdate(BaseModel):
    enabled: bool
    channel: str | None = None
    # Comma-separated ratings that count as actionable (e.g. "BUY,SELL").
    threshold: str | None = None

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_CHANNELS:
            raise ValueError(f"unknown channel: {v}")
        return v

    @field_validator("threshold")
    @classmethod
    def _validate_threshold(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = [p.strip() for p in v.split(",") if p.strip()]
        if not parts:
            raise ValueError("threshold must list at least one rating")
        return ",".join(parts)


class NotifyOut(BaseModel):
    enabled: bool
    channel: str
    threshold: str
    # Whether the chosen channel can actually deliver to this user right now
    # (email channel requires an email on record). The UI uses this to warn.
    deliverable: bool

    model_config = ConfigDict(from_attributes=False)

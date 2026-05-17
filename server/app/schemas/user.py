import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    id: uuid.UUID
    github_id: str
    email: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

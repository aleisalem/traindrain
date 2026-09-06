import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class GroupUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime

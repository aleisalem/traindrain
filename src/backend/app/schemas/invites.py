import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    language: Literal["en", "de"] = "en"


class InviteResponse(BaseModel):
    id: uuid.UUID
    email: str
    language: str
    expires_at: datetime
    roles: list[str]
    groups: list[str]


class InviteStatusResponse(BaseModel):
    email: str
    language: str


class InviteAcceptRequest(BaseModel):
    password: str


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str


class InviteExpirySettingResponse(BaseModel):
    days: int


class InviteExpirySettingRequest(BaseModel):
    days: int = Field(ge=1, le=365)

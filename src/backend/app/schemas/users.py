import uuid
from datetime import datetime

from pydantic import BaseModel


class UserListItem(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str | None
    last_name: str | None
    roles: list[str]
    disabled_at: datetime | None
    erased_at: datetime | None
    created_at: datetime

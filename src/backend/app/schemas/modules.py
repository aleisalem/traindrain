import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The languages the platform ships content in. Kept as a Literal rather than a
# free string so an unsupported language is a 422 at the edge, before it can
# reach the module row whose stored language later picks a text-search
# configuration.
ModuleLanguage = Literal["en", "de"]


class ModuleCreateRequest(BaseModel):
    # extra="forbid" is what makes an attempt to smuggle `created_by`,
    # `status`, or `draft_revision` into the payload a 422 rather than a
    # silently-ignored field — those are set server-side, never by the client.
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    language: ModuleLanguage
    description: str | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A module needs a title.")
        return value

    @field_validator("description")
    @classmethod
    def _blank_description_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ModuleUpdateRequest(BaseModel):
    """A partial update — a field left out is left alone.

    `language` is absent deliberately: it is fixed at creation, because the
    full-text search configuration for a module's pages is derived from it at
    write time. A different language is a new variant (ticket 6), not an edit.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A module needs a title.")
        return value

    @field_validator("description")
    @classmethod
    def _blank_description_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ModuleActor(BaseModel):
    """Who created or last edited a module.

    Carries a display name rather than the full user record: authoring must
    not become a route into the staff directory.
    """

    id: uuid.UUID
    display_name: str


class ModuleEditorsResponse(BaseModel):
    """Who else currently has this module open.

    Never includes the caller — the question the authoring screen is asking is
    "who am I sharing this with", and listing yourself back answers a
    different one.
    """

    editors: list[ModuleActor]


class PageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The module's optimistic-lock token, so two Content Managers editing the
    # same draft get a 409 rather than one silently overwriting the other.
    draft_revision: int
    title: str = Field(min_length=1, max_length=200)
    schema_version: int
    # Validated against the checked-in ProseMirror schema in the route, not
    # here: pydantic can say "this is an object", but only
    # `app.content.validation` can say the document conforms.
    body: dict[str, Any]

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A page needs a title.")
        return value


class PageUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    schema_version: int | None = None
    body: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A page needs a title.")
        return value


class PageDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int


class PageReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int
    # Every one of the module's page ids, exactly once, in the order wanted.
    page_ids: list[uuid.UUID] = Field(min_length=1)


class PageResponse(BaseModel):
    id: uuid.UUID
    position: int
    title: str
    schema_version: int
    body: dict[str, Any]
    updated_at: datetime


class PagesResponse(BaseModel):
    """A module's draft pages, with the token the next write has to carry."""

    draft_revision: int
    schema_version: int
    pages: list[PageResponse]


class ModuleResponse(BaseModel):
    id: uuid.UUID
    translation_group_id: uuid.UUID
    language: str
    title: str
    description: str | None
    estimated_duration_minutes: int | None
    status: str
    created_by: ModuleActor
    last_edited_by: ModuleActor
    created_at: datetime
    updated_at: datetime

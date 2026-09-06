from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UpdateNameRequest(BaseModel):
    # extra="forbid" is what makes an attempt to smuggle `email` (or anything
    # else) into this payload a 422 rather than a silently-ignored field —
    # email is immutable and isn't a field this endpoint accepts at all.
    model_config = ConfigDict(extra="forbid")

    # max_length matches users.first_name/last_name (VARCHAR(100)) so an
    # over-long name is a clean 422 here rather than a database error.
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    @field_validator("first_name", "last_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class UpdatePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_language: Literal["en", "de"]
    preferred_theme: Literal["light", "dark", "colorblind"]


class ProfileResponse(BaseModel):
    id: str
    email: str
    first_name: str | None
    last_name: str | None
    preferred_language: str | None
    preferred_theme: str | None

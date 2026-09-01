from pydantic import BaseModel


class LoginRequest(BaseModel):
    # Not EmailStr: this is matched against an existing stored email, not
    # validated as a new, deliverable address (that belongs at invite time,
    # ticket 5) — EmailStr would reject reserved-TLD addresses like the
    # bootstrap admin's own default `admin@traindrain.local`, and login
    # should fail with the same generic "invalid credentials" as any other
    # non-matching value rather than a format-validation error.
    email: str
    password: str


class LoginResponse(BaseModel):
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MeResponse(BaseModel):
    id: str
    email: str
    first_name: str | None
    last_name: str | None
    must_change_password: bool
    roles: list[str]

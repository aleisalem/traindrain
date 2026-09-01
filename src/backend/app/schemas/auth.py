from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
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

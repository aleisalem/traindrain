from pydantic import BaseModel, EmailStr


class TwoFactorEnrollResponse(BaseModel):
    secret: str
    qr_code_data_uri: str


class TwoFactorCodeRequest(BaseModel):
    code: str


class TwoFactorEnableResponse(BaseModel):
    recovery_codes: list[str]


class TwoFactorDisableRequest(BaseModel):
    password: str


class AdminTwoFactorDisableRequest(BaseModel):
    # An admin identifies the target by email rather than user id — there's no
    # user-listing endpoint yet (that's ticket 9) for an admin shell page to
    # pick an id from.
    email: EmailStr

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_session, require_active_user
from app.models import RecoveryCode, TwoFactorCredential, User
from app.models import Session as SessionModel
from app.schemas.auth import LoginResponse
from app.schemas.two_factor import (
    TwoFactorCodeRequest,
    TwoFactorDisableRequest,
    TwoFactorEnableResponse,
    TwoFactorEnrollResponse,
)
from app.security.crypto import encrypt_secret
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import is_rate_limited, record_failed_login_attempt
from app.security.sessions import (
    CHALLENGE_COOKIE_NAME,
    clear_challenge_cookie,
    create_session,
    get_valid_two_factor_challenge,
    revoke_other_sessions,
    set_session_cookie,
)
from app.security.totp import (
    generate_recovery_codes,
    generate_totp_secret,
    provisioning_uri,
    qr_code_data_uri,
    verify_totp_code,
)
from app.security.two_factor import delete_two_factor_credential

router = APIRouter(prefix="/api/auth/2fa", tags=["two-factor"])

_INVALID_CODE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid two-factor code."
)


def _client_ip(request: Request) -> str:
    # Same reasoning as the login endpoint — see app/routes/auth.py.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/enroll", response_model=TwoFactorEnrollResponse)
async def enroll(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> TwoFactorEnrollResponse:
    existing = await db.get(TwoFactorCredential, user.id)
    if existing is not None and existing.enabled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor authentication is already enabled.",
        )

    secret = generate_totp_secret()
    encrypted = encrypt_secret(secret)
    if existing is not None:
        # Re-enrolling over a still-unconfirmed setup discards the old secret.
        existing.encrypted_secret = encrypted
    else:
        db.add(TwoFactorCredential(user_id=user.id, encrypted_secret=encrypted))
    await db.commit()

    uri = provisioning_uri(secret, account_email=user.email)
    return TwoFactorEnrollResponse(secret=secret, qr_code_data_uri=qr_code_data_uri(uri))


@router.post("/enable", response_model=TwoFactorEnableResponse)
async def enable(
    payload: TwoFactorCodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
    session: SessionModel = Depends(get_current_session),
) -> TwoFactorEnableResponse:
    credential = await db.get(TwoFactorCredential, user.id)
    if credential is None or credential.enabled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start enrollment before enabling two-factor authentication.",
        )

    if not verify_totp_code(credential.encrypted_secret, payload.code):
        raise _INVALID_CODE

    credential.enabled_at = datetime.now(UTC)

    # Clears out any codes left over from a prior, never-confirmed
    # enroll/enable cycle so only the freshly issued batch is valid.
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = generate_recovery_codes()
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_password(code)))

    # Enabling 2FA is a security-posture change, same as a password change —
    # invalidate every other active session so it takes effect immediately.
    await revoke_other_sessions(db, user_id=user.id, keep_session_id=session.id)
    await db.commit()
    return TwoFactorEnableResponse(recovery_codes=codes)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable(
    payload: TwoFactorDisableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
    session: SessionModel = Depends(get_current_session),
) -> None:
    credential = await db.get(TwoFactorCredential, user.id)
    if credential is None or credential.enabled_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor authentication is not enabled.",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect."
        )

    await delete_two_factor_credential(db, user_id=user.id)

    # A security-posture downgrade, same as enabling — invalidate every other
    # active session so it takes effect immediately.
    await revoke_other_sessions(db, user_id=user.id, keep_session_id=session.id)
    await db.commit()


@router.post("/verify", response_model=LoginResponse)
async def verify(
    payload: TwoFactorCodeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    challenge_token: str | None = Cookie(default=None, alias=CHALLENGE_COOKIE_NAME),
) -> LoginResponse:
    if challenge_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No pending two-factor challenge."
        )

    challenge = await get_valid_two_factor_challenge(db, challenge_token)
    if challenge is None:
        clear_challenge_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This two-factor challenge has expired. Log in again.",
        )

    user = await db.get(User, challenge.user_id)
    credential = await db.get(TwoFactorCredential, challenge.user_id)
    if user is None or credential is None or credential.enabled_at is None:
        raise _INVALID_CODE

    ip_address = _client_ip(request)
    # Deliberately shares the login endpoint's (email, ip) attempt budget —
    # a 6-digit TOTP only has 1,000,000 possibilities, so this step needs the
    # same brute-force protection as the password step, not a separate one.
    if await is_rate_limited(db, email=user.email, ip_address=ip_address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
        )

    code_is_valid = verify_totp_code(
        credential.encrypted_secret, payload.code
    ) or await _consume_recovery_code(db, user_id=user.id, code=payload.code)

    if not code_is_valid:
        await record_failed_login_attempt(db, email=user.email, ip_address=ip_address)
        raise _INVALID_CODE

    challenge.consumed_at = datetime.now(UTC)
    clear_challenge_cookie(response)
    _session, token = await create_session(db, user_id=user.id)
    set_session_cookie(response, token)
    await db.commit()

    return LoginResponse(must_change_password=user.must_change_password)


async def _consume_recovery_code(db: AsyncSession, *, user_id: uuid.UUID, code: str) -> bool:
    candidates = (
        await db.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None)
            )
        )
    ).scalars()
    normalized = code.strip().upper()
    for candidate in candidates:
        if verify_password(normalized, candidate.code_hash):
            candidate.used_at = datetime.now(UTC)
            return True
    return False

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.dependencies import (
    get_current_session,
    get_current_user,
    get_http_client,
    get_ses_client,
    require_active_user,
)
from app.models import PasswordResetToken, User
from app.models import Session as SessionModel
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ResetPasswordRequest,
)
from app.security.mailer import SESClient, send_password_reset_email
from app.security.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.security.rate_limit import is_rate_limited, record_failed_login_attempt
from app.security.sessions import (
    clear_session_cookie,
    create_session,
    revoke_other_sessions,
    revoke_session,
    set_session_cookie,
)
from app.security.tokens import generate_token, hash_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
)

# Shorter than the invite expiry (7 days) since this is a security-sensitive
# action-in-progress rather than an onboarding grace period.
RESET_TOKEN_LIFETIME = timedelta(hours=1)

# Deliberately generic and identical for "never existed", "expired",
# "already used", and "superseded by a later request" — a caller doesn't
# need (or get) to distinguish those.
_RESET_TOKEN_NO_LONGER_VALID = HTTPException(
    status_code=status.HTTP_410_GONE, detail="This password reset link is no longer valid."
)

# Verified against on every "unknown email" login, so that path costs the same
# Argon2id hash comparison as a "wrong password" one — otherwise an unknown
# email would respond measurably faster, defeating the generic error message's
# purpose of not letting a caller enumerate which emails have accounts.
_DUMMY_PASSWORD_HASH = hash_password(generate_token())


def _client_ip(request: Request) -> str:
    # Both docker-compose's nginx and the production ALB terminate the only
    # hop between a real client and this app — it's never exposed directly to
    # the internet — so the first X-Forwarded-For entry is the real client IP.
    # request.client.host alone would be the proxy's own address.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    ip_address = _client_ip(request)

    if await is_rate_limited(db, email=payload.email, ip_address=ip_address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    user = (
        await db.execute(
            select(User).where(func.lower(User.email) == payload.email.strip().lower())
        )
    ).scalar_one_or_none()

    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    if user is None or not verify_password(payload.password, password_hash):
        await record_failed_login_attempt(db, email=payload.email, ip_address=ip_address)
        raise _INVALID_CREDENTIALS

    _session, token = await create_session(db, user_id=user.id)
    set_session_cookie(response, token)
    return LoginResponse(must_change_password=user.must_change_password)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    session: SessionModel = Depends(get_current_session),
) -> None:
    await revoke_session(db, session)
    clear_session_cookie(response)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(require_active_user)) -> MeResponse:
    return MeResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        must_change_password=user.must_change_password,
        roles=[role.name for role in user.roles],
    )


@router.post("/change-password", response_model=LoginResponse)
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    session: SessionModel = Depends(get_current_session),
    user: User = Depends(get_current_user),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> LoginResponse:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect."
        )

    try:
        await validate_password_policy(payload.new_password, http_client=http_client)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"reasons": exc.reasons}
        ) from exc

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    await revoke_other_sessions(db, user_id=user.id, keep_session_id=session.id)
    await db.commit()

    return LoginResponse(must_change_password=False)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    ses_client: SESClient = Depends(get_ses_client),
) -> None:
    # Always responds 204 regardless of whether the email matches an account
    # — the response must never leak account existence.
    user = (
        await db.execute(
            select(User).where(func.lower(User.email) == payload.email.strip().lower())
        )
    ).scalar_one_or_none()
    if user is None:
        return

    now = datetime.now(UTC)

    # A fresh request supersedes any still-pending one, the same way a
    # re-invite supersedes a prior pending invite.
    prior_tokens = (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        )
    ).scalars()
    for prior in prior_tokens:
        prior.used_at = now

    token = generate_token()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + RESET_TOKEN_LIFETIME,
    )
    db.add(reset_token)

    reset_url = f"{get_settings().frontend_base_url}/reset-password?token={token}"
    await send_password_reset_email(
        ses_client,
        to_email=user.email,
        language=user.preferred_language or "en",
        reset_url=reset_url,
    )

    # Committed only after the email send succeeds, so a failed send leaves
    # no half-issued token (and any prior token it would have superseded
    # stays valid) — the caller can just retry.
    await db.commit()


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> None:
    reset_token = (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_token(payload.token)
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if reset_token is None or reset_token.used_at is not None or reset_token.expires_at <= now:
        raise _RESET_TOKEN_NO_LONGER_VALID

    try:
        await validate_password_policy(payload.password, http_client=http_client)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"reasons": exc.reasons}
        ) from exc

    user = (await db.execute(select(User).where(User.id == reset_token.user_id))).scalar_one()

    user.password_hash = hash_password(payload.password)
    user.must_change_password = False
    reset_token.used_at = now
    await revoke_other_sessions(db, user_id=user.id, keep_session_id=None)
    await db.commit()

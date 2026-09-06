import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session as SessionModel
from app.models import TwoFactorChallenge
from app.security.tokens import generate_token, hash_token

COOKIE_NAME = "traindrain_session"

# Fixed per the Release 0 spec — not admin-configurable, unlike invite expiry.
ABSOLUTE_LIFETIME = timedelta(hours=12)
IDLE_TIMEOUT = timedelta(minutes=30)

# A 2FA-pending "half login" — deliberately much shorter-lived than a real
# session, since it exists only to bridge "password verified" and "second
# factor verified".
CHALLENGE_COOKIE_NAME = "traindrain_2fa_challenge"
CHALLENGE_LIFETIME = timedelta(minutes=5)
# Scoped so the browser only ever sends it to the 2FA endpoints that need it,
# not to every request the way the real session cookie is.
CHALLENGE_COOKIE_PATH = "/api/auth/2fa"


async def create_session(db: AsyncSession, *, user_id: uuid.UUID) -> tuple[SessionModel, str]:
    """Create a server-side session row and return it with its raw (unhashed) token."""
    token = generate_token()
    now = datetime.now(UTC)
    session = SessionModel(
        user_id=user_id,
        token_hash=hash_token(token),
        last_active_at=now,
        expires_at=now + ABSOLUTE_LIFETIME,
    )
    db.add(session)
    await db.commit()
    return session, token


async def get_valid_session(db: AsyncSession, token: str) -> SessionModel | None:
    """Look up a session by its raw token, enforcing absolute and idle expiry.

    A live, non-expired session has its idle clock reset as a side effect.
    """
    now = datetime.now(UTC)
    session = (
        await db.execute(select(SessionModel).where(SessionModel.token_hash == hash_token(token)))
    ).scalar_one_or_none()

    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= now:
        return None
    if now - session.last_active_at > IDLE_TIMEOUT:
        session.revoked_at = now
        await db.commit()
        return None

    session.last_active_at = now
    await db.commit()
    return session


async def revoke_session(db: AsyncSession, session: SessionModel) -> None:
    session.revoked_at = datetime.now(UTC)
    await db.commit()


async def revoke_other_sessions(
    db: AsyncSession, *, user_id: uuid.UUID, keep_session_id: uuid.UUID | None = None
) -> None:
    """Revoke every active session for a user except the one currently in use."""
    now = datetime.now(UTC)
    sessions = (
        await db.execute(
            select(SessionModel).where(
                SessionModel.user_id == user_id, SessionModel.revoked_at.is_(None)
            )
        )
    ).scalars()
    for session in sessions:
        if session.id != keep_session_id:
            session.revoked_at = now
    await db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=int(ABSOLUTE_LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict")


async def create_two_factor_challenge(
    db: AsyncSession, *, user_id: uuid.UUID
) -> tuple[TwoFactorChallenge, str]:
    """Create a pending-2FA challenge row and return it with its raw token."""
    token = generate_token()
    now = datetime.now(UTC)
    challenge = TwoFactorChallenge(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=now + CHALLENGE_LIFETIME,
    )
    db.add(challenge)
    await db.commit()
    return challenge, token


async def get_valid_two_factor_challenge(
    db: AsyncSession, token: str
) -> TwoFactorChallenge | None:
    """Look up a pending challenge by its raw token, enforcing expiry/single-use."""
    now = datetime.now(UTC)
    challenge = (
        await db.execute(
            select(TwoFactorChallenge).where(TwoFactorChallenge.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()

    if challenge is None or challenge.consumed_at is not None or challenge.expires_at <= now:
        return None
    return challenge


def set_challenge_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CHALLENGE_COOKIE_NAME,
        value=token,
        max_age=int(CHALLENGE_LIFETIME.total_seconds()),
        path=CHALLENGE_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )


def clear_challenge_cookie(response: Response) -> None:
    response.delete_cookie(
        key=CHALLENGE_COOKIE_NAME,
        path=CHALLENGE_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )

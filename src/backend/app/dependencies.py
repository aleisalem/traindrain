from collections.abc import AsyncIterator

import boto3
import httpx
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.models import Session as SessionModel
from app.models import User
from app.security.mailer import SESClient
from app.security.sessions import COOKIE_NAME, get_valid_session

_NOT_AUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
)


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        yield client


def get_ses_client() -> SESClient:
    settings = get_settings()
    client_kwargs: dict[str, str] = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        client_kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("ses", **client_kwargs)


async def get_current_session(
    db: AsyncSession = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> SessionModel:
    if session_token is None:
        raise _NOT_AUTHENTICATED
    session = await get_valid_session(db, session_token)
    if session is None:
        raise _NOT_AUTHENTICATED
    return session


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    session: SessionModel = Depends(get_current_session),
) -> User:
    user = await db.get(User, session.user_id)
    if user is None or user.disabled_at is not None:
        raise _NOT_AUTHENTICATED
    return user


async def require_active_user(user: User = Depends(get_current_user)) -> User:
    """Gate for every endpoint except "change my password" and session/self-status checks.

    A user with `must_change_password` set can still check their own session
    status and log out — but nothing else — until they've set a new password.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "You must set a new password before continuing.",
            },
        )
    return user


async def require_administrator(user: User = Depends(require_active_user)) -> User:
    """Gate for admin-only endpoints — implicit deny for every other role."""
    if "Administrator" not in {role.name for role in user.roles}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
    return user

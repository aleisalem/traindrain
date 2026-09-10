import uuid
from collections.abc import AsyncIterator
from typing import Any

import boto3
import httpx
from botocore.config import Config
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import AUTHORING_ROLES
from app.core.config import get_settings
from app.db import get_db
from app.models import Module, User
from app.models import Session as SessionModel
from app.security.mailer import SESClient
from app.security.sessions import COOKIE_NAME, get_valid_session
from app.storage import S3Client

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


def _s3_client(endpoint_url: str | None) -> S3Client:
    """An S3 client against one endpoint.

    Signed with SigV4 explicitly: a presigned URL from the default signer can
    come back as SigV2 against some endpoints, which several S3-compatible
    implementations reject outright.
    """
    client_kwargs: dict[str, Any] = {
        "region_name": get_settings().aws_region,
        "config": Config(signature_version="s3v4"),
    }
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **client_kwargs)


def get_s3_client() -> S3Client:
    """The client that reads and writes asset objects."""
    return _s3_client(get_settings().aws_endpoint_url)


def get_asset_signing_client() -> S3Client:
    """The client that mints presigned URLs a *browser* will follow.

    Separate from `get_s3_client` because a URL is only useful to whoever has
    to fetch it: inside docker-compose the API reaches LocalStack at
    `http://localstack:4566`, a hostname that means nothing on the developer's
    machine. Signing against the browser-facing endpoint is what makes the
    redirect land. In production no override is set and this is the same client.
    """
    settings = get_settings()
    return _s3_client(settings.s3_public_endpoint_url or settings.aws_endpoint_url)


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


async def require_content_manager(user: User = Depends(require_active_user)) -> User:
    """Gate for the authoring endpoints — Content Managers and Administrators only.

    Deliberately *not* the inverse of `require_administrator`: this admits
    Administrators too (they have read-and-write access to everything), while
    `require_administrator` still admits nobody else. No Release 0 boundary
    moves — a Content Manager gets a 403 from `/api/admin/*` exactly as a
    Learner does.
    """
    if not AUTHORING_ROLES & {role.name for role in user.roles}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
    return user


async def get_module_or_404(
    db: AsyncSession, module_id: uuid.UUID, *, for_update: bool = False
) -> Module:
    """Load a module, optionally taking its row lock first.

    Shared by every route that addresses a module by id, so "does this exist"
    has one answer and one status code.

    `for_update` is what makes `draft_revision` an actual lock rather than a
    check: without it, two simultaneous saves can both read revision 1, both
    find it current, and both write revision 2 — the lost update the token
    exists to prevent. Every draft mutation takes the lock; reads don't.
    """
    statement = select(Module).where(Module.id == module_id)
    if for_update:
        statement = statement.with_for_update()
    module = (await db.execute(statement)).scalar_one_or_none()
    if module is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found.")
    return module

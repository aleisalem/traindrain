from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_http_client
from app.models import Invite, Role, User
from app.schemas.invites import InviteAcceptRequest, InviteStatusResponse
from app.security.passwords import PasswordPolicyError, hash_password, validate_password_policy
from app.security.tokens import hash_token

router = APIRouter(prefix="/api/invites", tags=["invites"])

# Deliberately generic and identical for "never existed", "expired", "already
# used", and "revoked by a re-invite" — a visitor doesn't need (or get) to
# distinguish those, and it avoids leaking which reason applies.
_INVITE_NO_LONGER_VALID = HTTPException(
    status_code=status.HTTP_410_GONE, detail="This invite is no longer valid."
)


async def _load_valid_invite(db: AsyncSession, token: str) -> Invite:
    invite = (
        await db.execute(select(Invite).where(Invite.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if invite is None:
        raise _INVITE_NO_LONGER_VALID
    now = datetime.now(UTC)
    if invite.accepted_at is not None or invite.revoked_at is not None or invite.expires_at <= now:
        raise _INVITE_NO_LONGER_VALID
    return invite


@router.get("/{token}", response_model=InviteStatusResponse)
async def get_invite_status(token: str, db: AsyncSession = Depends(get_db)) -> InviteStatusResponse:
    invite = await _load_valid_invite(db, token)
    return InviteStatusResponse(email=invite.email, language=invite.language)


@router.post("/{token}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invite(
    token: str,
    payload: InviteAcceptRequest,
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> None:
    invite = await _load_valid_invite(db, token)

    try:
        await validate_password_policy(payload.password, http_client=http_client)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"reasons": exc.reasons}
        ) from exc

    learner_role = (await db.execute(select(Role).where(Role.name == "Learner"))).scalar_one()
    roles_by_id = {learner_role.id: learner_role}
    for role in invite.roles:
        roles_by_id[role.id] = role

    user = User(
        email=invite.email,
        password_hash=hash_password(payload.password),
        preferred_language=invite.language,
        roles=list(roles_by_id.values()),
        groups=list(invite.groups),
    )
    db.add(user)
    invite.accepted_at = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        # A concurrent accept (or an account created some other way in the
        # meantime) raced this one — treat it the same as any other
        # no-longer-valid invite rather than a raw 500.
        await db.rollback()
        raise _INVITE_NO_LONGER_VALID from exc

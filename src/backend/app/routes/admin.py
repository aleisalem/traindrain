from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.dependencies import get_ses_client, require_administrator
from app.models import Invite, Role, User
from app.schemas.invites import (
    InviteCreateRequest,
    InviteExpirySettingRequest,
    InviteExpirySettingResponse,
    InviteResponse,
    RoleResponse,
)
from app.security.audit import record_audit_log
from app.security.mailer import SESClient, send_invite_email
from app.security.system_settings import get_invite_expiry_days, set_invite_expiry_days
from app.security.tokens import generate_token, hash_token

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/ping")
async def admin_ping(user: User = Depends(require_administrator)) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> list[RoleResponse]:
    roles = (await db.execute(select(Role).order_by(Role.name))).scalars()
    return [RoleResponse(id=role.id, name=role.name) for role in roles]


@router.get("/settings/invite-expiry-days", response_model=InviteExpirySettingResponse)
async def get_invite_expiry_setting(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> InviteExpirySettingResponse:
    return InviteExpirySettingResponse(days=await get_invite_expiry_days(db))


@router.put("/settings/invite-expiry-days", response_model=InviteExpirySettingResponse)
async def update_invite_expiry_setting(
    payload: InviteExpirySettingRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> InviteExpirySettingResponse:
    await set_invite_expiry_days(db, payload.days)
    return InviteExpirySettingResponse(days=payload.days)


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
    ses_client: SESClient = Depends(get_ses_client),
) -> InviteResponse:
    normalized_email = payload.email.strip().lower()

    existing_user = (
        await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    roles: list[Role] = []
    if payload.role_ids:
        roles = list(
            (await db.execute(select(Role).where(Role.id.in_(payload.role_ids)))).scalars()
        )
        if len(roles) != len(set(payload.role_ids)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="One or more role ids are invalid.",
            )

    now = datetime.now(UTC)

    # Re-inviting the same email invalidates any prior pending invite to it.
    prior_pending_invites = (
        await db.execute(
            select(Invite).where(
                func.lower(Invite.email) == normalized_email,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
            )
        )
    ).scalars()
    for prior in prior_pending_invites:
        prior.revoked_at = now

    expiry_days = await get_invite_expiry_days(db)
    token = generate_token()
    invite = Invite(
        email=payload.email.strip(),
        token_hash=hash_token(token),
        language=payload.language,
        invited_by_user_id=admin.id,
        expires_at=now + timedelta(days=expiry_days),
        roles=roles,
    )
    db.add(invite)
    await db.flush()

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="invite_sent",
        detail={
            "email": invite.email,
            "language": invite.language,
            "roles": sorted(role.name for role in roles),
        },
    )

    accept_url = f"{get_settings().frontend_base_url}/accept-invite?token={token}"
    await send_invite_email(
        ses_client, to_email=invite.email, language=invite.language, accept_url=accept_url
    )

    # Committed only after the email send succeeds, so a failed send leaves
    # no half-issued invite (and any prior invite it would have revoked stays
    # valid) — the admin can just retry.
    await db.commit()

    return InviteResponse(
        id=invite.id,
        email=invite.email,
        language=invite.language,
        expires_at=invite.expires_at,
        roles=[role.name for role in roles],
    )

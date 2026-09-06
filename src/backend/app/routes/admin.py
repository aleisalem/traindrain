import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.dependencies import get_current_session, get_ses_client, require_administrator
from app.models import Group, Invite, Role, TwoFactorCredential, User
from app.models import Session as SessionModel
from app.schemas.groups import GroupCreateRequest, GroupResponse, GroupUpdateRequest
from app.schemas.invites import (
    InviteCreateRequest,
    InviteExpirySettingRequest,
    InviteExpirySettingResponse,
    InviteResponse,
    RoleResponse,
)
from app.schemas.two_factor import AdminTwoFactorDisableRequest
from app.schemas.users import UserListItem
from app.security.audit import record_audit_log
from app.security.mailer import SESClient, send_invite_email
from app.security.passwords import hash_password
from app.security.sessions import revoke_other_sessions
from app.security.system_settings import get_invite_expiry_days, set_invite_expiry_days
from app.security.tokens import generate_token, hash_token
from app.security.two_factor import delete_two_factor_credential

router = APIRouter(prefix="/api/admin", tags=["admin"])

_USER_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


async def _get_target_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    # A select(), not db.get() — db.get() short-circuits on an
    # already-identity-mapped row without applying the mapper's selectin
    # eager loads, which can leave a lazy="selectin" collection (like
    # `groups`) unloaded and unable to lazy-load in an async context.
    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise _USER_NOT_FOUND
    return target


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


@router.get("/users", response_model=list[UserListItem])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> list[UserListItem]:
    users = (await db.execute(select(User).order_by(User.created_at))).scalars()
    return [
        UserListItem(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            roles=[role.name for role in user.roles],
            disabled_at=user.disabled_at,
            erased_at=user.erased_at,
            created_at=user.created_at,
        )
        for user in users
    ]


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
    await db.commit()
    return InviteExpirySettingResponse(days=payload.days)


@router.post("/users/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def admin_disable_two_factor(
    payload: AdminTwoFactorDisableRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    normalized_email = payload.email.strip().lower()
    target = (
        await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No user found with that email."
        )

    credential = await db.get(TwoFactorCredential, target.id)
    if credential is None or credential.enabled_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor authentication is not enabled for this user.",
        )

    await delete_two_factor_credential(db, user_id=target.id)

    # An out-of-band recovery, not the target acting for themselves — there's
    # no "current session" of theirs to spare, unlike a self-service change.
    await revoke_other_sessions(db, user_id=target.id, keep_session_id=None)

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="two_factor_admin_disabled",
        target_user_id=target.id,
        detail={"email": target.email},
    )
    await db.commit()


# Registered after the literal /users/2fa/disable route above — Starlette
# matches path routes in registration order, and {user_id} would otherwise
# swallow "2fa" as its value and fail UUID parsing before reaching it.
@router.post("/users/{user_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You cannot disable your own account."
        )
    target = await _get_target_user(db, user_id)
    if target.disabled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is already disabled."
        )

    target.disabled_at = datetime.now(UTC)
    await revoke_other_sessions(db, user_id=target.id, keep_session_id=None)

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="user_disabled",
        target_user_id=target.id,
        detail={"email": target.email},
    )
    await db.commit()


@router.post("/users/{user_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    target = await _get_target_user(db, user_id)
    if target.erased_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user has been erased."
        )
    if target.disabled_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is not disabled."
        )

    target.disabled_at = None

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="user_enabled",
        target_user_id=target.id,
        detail={"email": target.email},
    )
    await db.commit()


@router.post("/users/{user_id}/erase", status_code=status.HTTP_204_NO_CONTENT)
async def erase_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You cannot erase your own account."
        )
    target = await _get_target_user(db, user_id)
    if target.erased_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user has already been erased."
        )

    now = datetime.now(UTC)

    # Keeps the row (a tombstone) so audit-log and future grading-record
    # foreign keys still resolve, while removing the personal fields the
    # right-to-erasure request covers. The email must stay unique — the
    # user's own id guarantees that deterministically.
    target.email = f"erased-user-{target.id}@erased.invalid"
    target.first_name = None
    target.last_name = None
    # Replaces the password hash with one derived from a random, discarded
    # value — this account is erased and disabled, so nothing should ever be
    # able to authenticate as it again.
    target.password_hash = hash_password(generate_token())
    target.erased_at = now
    target.disabled_at = now
    await revoke_other_sessions(db, user_id=target.id, keep_session_id=None)

    # No email in the detail blob, unlike the disable/enable log entries —
    # logging the erased personal data right back into a permanent audit
    # record would defeat the point of a right-to-erasure request.
    # target_user_id alone is enough to trace the action against the
    # tombstone row.
    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="user_erased",
        target_user_id=target.id,
    )
    await db.commit()


async def _get_target_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    return role


@router.get("/roles/{role_id}/members", response_model=list[UserListItem])
async def list_role_members(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> list[UserListItem]:
    role = await _get_target_role(db, role_id)
    users = (await db.execute(select(User).order_by(User.created_at))).scalars()
    return [
        UserListItem(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            roles=[r.name for r in user.roles],
            disabled_at=user.disabled_at,
            erased_at=user.erased_at,
            created_at=user.created_at,
        )
        for user in users
        if role in user.roles
    ]


@router.post("/users/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def assign_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
    session: SessionModel = Depends(get_current_session),
) -> None:
    target = await _get_target_user(db, user_id)
    role = await _get_target_role(db, role_id)
    if target.erased_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user has been erased."
        )
    if role in target.roles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user already has this role."
        )

    target.roles.append(role)
    # An admin changing their own roles keeps their current session — every
    # other active session for the target (including all of a different
    # user's) is revoked, so the access change takes effect immediately.
    await revoke_other_sessions(
        db, user_id=target.id, keep_session_id=session.id if target.id == admin.id else None
    )

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="role_assigned",
        target_user_id=target.id,
        detail={"role": role.name},
    )
    await db.commit()


@router.delete("/users/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
    session: SessionModel = Depends(get_current_session),
) -> None:
    target = await _get_target_user(db, user_id)
    role = await _get_target_role(db, role_id)
    # No erased-account guard here (unlike assign_role): erasure never clears
    # role membership, and stripping a stale role from a tombstone is exactly
    # the kind of cleanup this endpoint should allow rather than block.
    if role not in target.roles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user does not have this role."
        )

    target.roles.remove(role)
    await revoke_other_sessions(
        db, user_id=target.id, keep_session_id=session.id if target.id == admin.id else None
    )

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="role_removed",
        target_user_id=target.id,
        detail={"role": role.name},
    )
    await db.commit()


async def _get_target_group(db: AsyncSession, group_id: uuid.UUID) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
    return group


def _to_group_response(group: Group) -> GroupResponse:
    return GroupResponse(
        id=group.id, name=group.name, description=group.description, created_at=group.created_at
    )


@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> list[GroupResponse]:
    groups = (await db.execute(select(Group).order_by(Group.name))).scalars()
    return [_to_group_response(group) for group in groups]


@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> GroupResponse:
    existing = (
        await db.execute(select(Group).where(func.lower(Group.name) == payload.name.strip().lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A group with this name already exists."
        )

    group = Group(name=payload.name.strip(), description=payload.description)
    db.add(group)
    await db.flush()

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="group_created",
        detail={"group_id": str(group.id), "name": group.name},
    )
    await db.commit()
    return _to_group_response(group)


@router.put("/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> GroupResponse:
    group = await _get_target_group(db, group_id)
    existing = (
        await db.execute(
            select(Group).where(
                func.lower(Group.name) == payload.name.strip().lower(), Group.id != group_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A group with this name already exists."
        )

    group.name = payload.name.strip()
    group.description = payload.description

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="group_updated",
        detail={"group_id": str(group.id), "name": group.name},
    )
    await db.commit()
    return _to_group_response(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    group = await _get_target_group(db, group_id)
    name = group.name
    await db.delete(group)

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="group_deleted",
        detail={"group_id": str(group_id), "name": name},
    )
    await db.commit()


@router.get("/groups/{group_id}/members", response_model=list[UserListItem])
async def list_group_members(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> list[UserListItem]:
    group = await _get_target_group(db, group_id)
    users = (await db.execute(select(User).order_by(User.created_at))).scalars()
    return [
        UserListItem(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            roles=[role.name for role in user.roles],
            disabled_at=user.disabled_at,
            erased_at=user.erased_at,
            created_at=user.created_at,
        )
        for user in users
        if group in user.groups
    ]


@router.post("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    group = await _get_target_group(db, group_id)
    target = await _get_target_user(db, user_id)
    if target.erased_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user has been erased."
        )
    if group in target.groups:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is already a member of this group."
        )

    target.groups.append(group)

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="group_member_added",
        target_user_id=target.id,
        detail={"group_id": str(group.id), "group_name": group.name},
    )
    await db.commit()


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> None:
    group = await _get_target_group(db, group_id)
    target = await _get_target_user(db, user_id)
    # No erased-account guard here (unlike add_group_member): erasure never
    # clears group membership, and stripping a stale membership from a
    # tombstone is exactly the kind of cleanup this endpoint should allow.
    if group not in target.groups:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is not a member of this group."
        )

    target.groups.remove(group)

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="group_member_removed",
        target_user_id=target.id,
        detail={"group_id": str(group.id), "group_name": group.name},
    )
    await db.commit()


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

    groups: list[Group] = []
    if payload.group_ids:
        groups = list(
            (await db.execute(select(Group).where(Group.id.in_(payload.group_ids)))).scalars()
        )
        if len(groups) != len(set(payload.group_ids)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="One or more group ids are invalid.",
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
        groups=groups,
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
            "groups": sorted(group.name for group in groups),
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
        groups=[group.name for group in groups],
    )

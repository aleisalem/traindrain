"""Campaign drafts: a Content Manager builds a programme before anyone sees it.

Two rules shape every route here. First, a campaign belongs to the people
working on it — its creator, the collaborators the creator invited, and
Administrators: anyone else gets a 404, never a 403, so another team's
programmes cannot even be confirmed to exist. Second, naming a person is an
Administrator's act, as it is for assignments — a Content Manager picks
groups from the counts-only `GET /api/content/groups`.

A draft is inert: nothing here makes a campaign visible to a learner or sends
an email. That arrives with activation.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import ColumnElement, delete, exists, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import is_administrator, is_author
from app.db import get_db
from app.dependencies import require_content_manager
from app.models import (
    Campaign,
    CampaignCollaborator,
    CampaignEditSession,
    CampaignModule,
    CampaignTarget,
    Group,
    Module,
    ModuleTranslationGroup,
    User,
)
from app.routes.content import PRESENCE_WINDOW
from app.schemas.campaigns import (
    CampaignCreateRequest,
    CampaignModuleInput,
    CampaignModuleResponse,
    CampaignResponse,
    CampaignSummaryResponse,
    CampaignTargetInput,
    CampaignTargetResponse,
    CampaignUpdateRequest,
    CollaboratorAddRequest,
    ModuleAvailability,
    OwnerChangeRequest,
)
from app.schemas.modules import ModuleActor, ModuleEditorsResponse
from app.security.audit import record_audit_log

router = APIRouter(prefix="/api/content/campaigns", tags=["campaigns"])



def _campaign_not_found() -> HTTPException:
    # A fresh instance per miss: a shared one would accumulate tracebacks.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")


def may_see_campaign(user: User, campaign: Campaign) -> bool:
    """The one answer to "does this campaign exist for this caller?".

    The creator, an invited collaborator, or an Administrator. Every route
    asks here, so widening it widens everywhere at once.
    """
    return (
        is_administrator(user)
        or campaign.created_by == user.id
        or any(row.user_id == user.id for row in campaign.collaborators)
    )


def may_manage_campaign(user: User, campaign: Campaign) -> bool:
    """Who controls the room: the creator or an Administrator. A collaborator
    edits the campaign but cannot add or remove people or delete the draft."""
    return is_administrator(user) or campaign.created_by == user.id


def visible_campaigns_clause(user: User) -> ColumnElement[bool]:
    """`may_see_campaign` as a WHERE clause, for list queries. Keep the two in step."""
    if is_administrator(user):
        return true()
    return or_(
        Campaign.created_by == user.id,
        exists().where(
            CampaignCollaborator.campaign_id == Campaign.id,
            CampaignCollaborator.user_id == user.id,
        ),
    )


async def _get_campaign_or_404(db: AsyncSession, campaign_id: uuid.UUID, caller: User) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or not may_see_campaign(caller, campaign):
        raise _campaign_not_found()
    return campaign


async def _get_managed_campaign(
    db: AsyncSession, campaign_id: uuid.UUID, caller: User
) -> Campaign:
    """404 for a non-participant, 403 for a collaborator who may not do this."""
    campaign = await _get_campaign_or_404(db, campaign_id, caller)
    if not may_manage_campaign(caller, campaign):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the campaign's creator or an Administrator may do this.",
        )
    return campaign


def _require_administrator_for_individuals(caller: User, targets: list[CampaignTargetInput]) -> None:
    if any(t.type == "user" for t in targets) and not is_administrator(caller):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Administrator may target a campaign at an individual.",
        )


async def _validate_modules(db: AsyncSession, modules: list[CampaignModuleInput]) -> None:
    """Every referenced translation group must exist. Whether it is published
    is deliberately not checked: a draft may reference unfinished material and
    reports it instead (`_module_responses`)."""
    ids = {m.translation_group_id for m in modules}
    if not ids:
        return
    found = set(
        (
            await db.execute(
                select(ModuleTranslationGroup.id).where(ModuleTranslationGroup.id.in_(ids))
            )
        ).scalars()
    )
    if found != ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found.")


async def _validate_targets(db: AsyncSession, targets: list[CampaignTargetInput]) -> None:
    for target in targets:
        if target.type == "group":
            if await db.get(Group, target.id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
        else:
            user = await db.get(User, target.id)
            if user is None or user.erased_at is not None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


def _sync_modules(campaign: Campaign, modules: list[CampaignModuleInput]) -> None:
    """Make the campaign's module list match `modules`, order included.

    Updates surviving rows in place rather than rebuilding them: the unique
    constraint on (campaign, group) would otherwise trip when a flush inserts
    a re-added row before it deletes the old one.
    """
    existing = {row.translation_group_id: row for row in campaign.modules}
    wanted = {m.translation_group_id for m in modules}
    for group_id, row in existing.items():
        if group_id not in wanted:
            campaign.modules.remove(row)
    for position, module in enumerate(modules):
        row = existing.get(module.translation_group_id)
        if row is None:
            campaign.modules.append(
                CampaignModule(
                    translation_group_id=module.translation_group_id,
                    position=position,
                    requirement=module.requirement,
                )
            )
        else:
            row.position = position
            row.requirement = module.requirement
    campaign.modules.sort(key=lambda row: row.position)


def _sync_targets(campaign: Campaign, targets: list[CampaignTargetInput]) -> None:
    existing = {(row.target_type, row.target_id): row for row in campaign.targets}
    wanted = {(t.type, t.id) for t in targets}
    for key, row in existing.items():
        if key not in wanted:
            campaign.targets.remove(row)
    for target in targets:
        if (target.type, target.id) not in existing:
            campaign.targets.append(CampaignTarget(target_type=target.type, target_id=target.id))


async def _module_responses(
    db: AsyncSession, campaign: Campaign
) -> list[CampaignModuleResponse]:
    group_ids = [row.translation_group_id for row in campaign.modules]
    variants: dict[uuid.UUID, list[Module]] = {}
    primaries: dict[uuid.UUID, uuid.UUID | None] = {}
    if group_ids:
        for module in (
            await db.execute(select(Module).where(Module.translation_group_id.in_(group_ids)))
        ).scalars():
            variants.setdefault(module.translation_group_id, []).append(module)
        for group in (
            await db.execute(
                select(ModuleTranslationGroup).where(ModuleTranslationGroup.id.in_(group_ids))
            )
        ).scalars():
            primaries[group.id] = group.primary_module_id

    responses = []
    for row in campaign.modules:
        group_variants = variants.get(row.translation_group_id, [])
        live = [m for m in group_variants if m.status != "deleted"]
        published = [m for m in live if m.status == "published"]
        availability: ModuleAvailability
        if published:
            availability = "published"
        elif live:
            availability = "unpublished"
        else:
            availability = "deleted"
        # Prefer the primary variant's title; fall back to whatever survives,
        # then to a tombstone's title.
        pool = published or live or group_variants
        chosen = next((m for m in pool if m.id == primaries.get(row.translation_group_id)), None)
        chosen = chosen or (pool[0] if pool else None)
        responses.append(
            CampaignModuleResponse(
                translation_group_id=row.translation_group_id,
                position=row.position,
                requirement=row.requirement,
                title=chosen.title if chosen else None,
                availability=availability,
            )
        )
    return responses


async def _target_responses(
    db: AsyncSession, campaign: Campaign, *, caller: User
) -> list[CampaignTargetResponse]:
    reveal_users = is_administrator(caller)
    responses = []
    for target in campaign.targets:
        name: str | None = None
        if target.target_type == "group":
            group = await db.get(Group, target.target_id)
            name = group.name if group else None
        elif reveal_users:
            user = await db.get(User, target.target_id)
            name = ModuleActor.from_user(user).display_name if user else None
        responses.append(
            CampaignTargetResponse(type=target.target_type, id=target.target_id, name=name)
        )
    return responses


async def _to_response(db: AsyncSession, campaign: Campaign, *, caller: User) -> CampaignResponse:
    creator = await db.get(User, campaign.created_by)
    collaborators = []
    for row in campaign.collaborators:
        member = await db.get(User, row.user_id)
        if member is not None:
            collaborators.append(ModuleActor.from_user(member))
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        sequential=campaign.sequential,
        auto_reminders=campaign.auto_reminders,
        start_date=campaign.start_date,
        due_date=campaign.due_date,
        created_by=ModuleActor.from_user(creator),
        collaborators=collaborators,
        can_manage=may_manage_campaign(caller, campaign),
        modules=await _module_responses(db, campaign),
        targets=await _target_responses(db, campaign, caller=caller),
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.get("", response_model=list[CampaignSummaryResponse])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> list[CampaignSummaryResponse]:
    """The campaigns this caller may see: their own, ones they collaborate on, or all (Administrator)."""
    campaigns = (
        (
            await db.execute(
                select(Campaign)
                .where(visible_campaigns_clause(caller))
                .order_by(Campaign.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        CampaignSummaryResponse(
            id=c.id,
            name=c.name,
            status=c.status,
            start_date=c.start_date,
            due_date=c.due_date,
            module_count=len(c.modules),
            target_count=len(c.targets),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in campaigns
    ]


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> CampaignResponse:
    _require_administrator_for_individuals(caller, payload.targets)
    await _validate_modules(db, payload.modules)
    await _validate_targets(db, payload.targets)

    campaign = Campaign(
        name=payload.name,
        description=payload.description,
        status="draft",
        sequential=payload.sequential,
        auto_reminders=payload.auto_reminders,
        start_date=payload.start_date,
        due_date=payload.due_date,
        created_by=caller.id,
    )
    db.add(campaign)
    _sync_modules(campaign, payload.modules)
    _sync_targets(campaign, payload.targets)
    await db.flush()

    await record_audit_log(
        db,
        actor_user_id=caller.id,
        action="campaign_created",
        detail={
            "campaign_id": str(campaign.id),
            "name": campaign.name,
            "module_count": len(payload.modules),
            "target_count": len(payload.targets),
        },
    )
    await db.commit()
    await db.refresh(campaign)
    return await _to_response(db, campaign, caller=caller)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> CampaignResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, caller)
    return await _to_response(db, campaign, caller=caller)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignUpdateRequest,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> CampaignResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, caller)
    fields = payload.model_fields_set

    if "targets" in fields and payload.targets is not None:
        # Naming a person is an Administrator's act both ways: a Content
        # Manager may neither add an individual nor strip one out.
        current_users = {t.target_id for t in campaign.targets if t.target_type == "user"}
        requested_users = {t.id for t in payload.targets if t.type == "user"}
        if current_users != requested_users and not is_administrator(caller):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an Administrator may target a campaign at an individual.",
            )
        await _validate_targets(
            db, [t for t in payload.targets if (t.type, t.id) not in
                 {(row.target_type, row.target_id) for row in campaign.targets}]
        )
    if "modules" in fields and payload.modules is not None:
        await _validate_modules(db, payload.modules)

    start = payload.start_date if "start_date" in fields else campaign.start_date
    due = payload.due_date if "due_date" in fields else campaign.due_date
    if start and due and due < start:
        raise HTTPException(
            status_code=422,
            detail="The due date cannot be before the start date.",
        )

    changed: list[str] = []
    for field in ("name", "description", "start_date", "due_date", "auto_reminders", "sequential"):
        if field in fields and getattr(payload, field) != getattr(campaign, field):
            setattr(campaign, field, getattr(payload, field))
            changed.append(field)
    if "modules" in fields and payload.modules is not None:
        _sync_modules(campaign, payload.modules)
        changed.append("modules")
    if "targets" in fields and payload.targets is not None:
        _sync_targets(campaign, payload.targets)
        changed.append("targets")

    if changed:
        # Child-row-only edits (modules, targets) leave the campaigns row
        # itself untouched, so `onupdate` would never fire and the list's
        # most-recently-updated ordering would go stale.
        campaign.updated_at = datetime.now(UTC)
        await record_audit_log(
            db,
            actor_user_id=caller.id,
            action="campaign_updated",
            detail={"campaign_id": str(campaign.id), "changed": changed},
        )
    await db.commit()
    await db.refresh(campaign)
    return await _to_response(db, campaign, caller=caller)


# --- Collaborators and ownership ---------------------------------------------


async def _find_eligible_user(db: AsyncSession, email: str) -> User:
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()
    if user is None or user.erased_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if not is_author(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a Content Manager or an Administrator can work on a campaign.",
        )
    return user


@router.post(
    "/{campaign_id}/collaborators", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED
)
async def add_collaborator(
    campaign_id: uuid.UUID,
    payload: CollaboratorAddRequest,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> CampaignResponse:
    campaign = await _get_managed_campaign(db, campaign_id, caller)
    user = await _find_eligible_user(db, payload.email)
    if user.id == campaign.created_by:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The creator is already on this campaign."
        )
    if any(row.user_id == user.id for row in campaign.collaborators):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already a collaborator."
        )
    campaign.collaborators.append(CampaignCollaborator(user_id=user.id, added_by=caller.id))
    campaign.updated_at = datetime.now(UTC)
    await record_audit_log(
        db,
        actor_user_id=caller.id,
        action="campaign_collaborator_added",
        detail={"campaign_id": str(campaign.id), "user_id": str(user.id)},
    )
    await db.commit()
    await db.refresh(campaign)
    return await _to_response(db, campaign, caller=caller)


@router.delete("/{campaign_id}/collaborators/{user_id}", response_model=CampaignResponse)
async def remove_collaborator(
    campaign_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> CampaignResponse:
    campaign = await _get_managed_campaign(db, campaign_id, caller)
    row = next((r for r in campaign.collaborators if r.user_id == user_id), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collaborator not found.")
    campaign.collaborators.remove(row)
    campaign.updated_at = datetime.now(UTC)
    await db.execute(
        delete(CampaignEditSession).where(
            CampaignEditSession.campaign_id == campaign.id,
            CampaignEditSession.user_id == user_id,
        )
    )
    await record_audit_log(
        db,
        actor_user_id=caller.id,
        action="campaign_collaborator_removed",
        detail={"campaign_id": str(campaign.id), "user_id": str(user_id)},
    )
    await db.commit()
    await db.refresh(campaign)
    return await _to_response(db, campaign, caller=caller)


@router.post("/{campaign_id}/owner", response_model=CampaignResponse)
async def reassign_owner(
    campaign_id: uuid.UUID,
    payload: OwnerChangeRequest,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> CampaignResponse:
    """Hand a campaign to another Content Manager — the way out of an orphan
    whose creator left or lost the role. Administrator-only."""
    campaign = await _get_campaign_or_404(db, campaign_id, caller)
    if not is_administrator(caller):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Administrator may reassign a campaign's creator.",
        )
    new_owner = await db.get(User, payload.user_id)
    if new_owner is None or new_owner.erased_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if not is_author(new_owner):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a Content Manager or an Administrator can own a campaign.",
        )
    if new_owner.id == campaign.created_by:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That user already owns this campaign."
        )
    previous = campaign.created_by
    # An owner is not also a collaborator.
    for row in [r for r in campaign.collaborators if r.user_id == new_owner.id]:
        campaign.collaborators.remove(row)
    campaign.created_by = new_owner.id
    campaign.updated_at = datetime.now(UTC)
    await record_audit_log(
        db,
        actor_user_id=caller.id,
        action="campaign_owner_changed",
        detail={
            "campaign_id": str(campaign.id),
            "previous_owner_id": str(previous),
            "new_owner_id": str(new_owner.id),
        },
    )
    await db.commit()
    await db.refresh(campaign)
    return await _to_response(db, campaign, caller=caller)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> None:
    """Hard-delete a draft. Creator or Administrator only; anything past draft
    is a conflict (the finer rules for campaigns that ran arrive with ticket 6)."""
    campaign = await _get_managed_campaign(db, campaign_id, caller)
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only a draft can be deleted."
        )
    await record_audit_log(
        db,
        actor_user_id=caller.id,
        action="campaign_deleted",
        detail={"campaign_id": str(campaign.id), "name": campaign.name},
    )
    await db.delete(campaign)
    await db.commit()


# --- Presence ------------------------------------------------------------------
# Same trade as module metadata: concurrent edits are allowed, so the screen
# says who else is here rather than locking anyone out.


@router.post("/{campaign_id}/editing", response_model=ModuleEditorsResponse)
async def heartbeat_editing(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> ModuleEditorsResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, caller)
    now = datetime.now(UTC)
    await db.execute(
        pg_insert(CampaignEditSession)
        .values(campaign_id=campaign.id, user_id=caller.id, last_seen_at=now)
        .on_conflict_do_update(
            index_elements=["campaign_id", "user_id"], set_={"last_seen_at": now}
        )
    )
    await db.execute(
        delete(CampaignEditSession).where(
            CampaignEditSession.campaign_id == campaign.id,
            CampaignEditSession.last_seen_at < now - PRESENCE_WINDOW,
        )
    )
    await db.commit()

    user_ids = list(
        (
            await db.execute(
                select(CampaignEditSession.user_id).where(
                    CampaignEditSession.campaign_id == campaign.id,
                    CampaignEditSession.last_seen_at >= now - PRESENCE_WINDOW,
                    CampaignEditSession.user_id != caller.id,
                )
            )
        ).scalars()
    )
    users = (
        (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars() if user_ids else []
    )
    return ModuleEditorsResponse(
        editors=sorted(
            (ModuleActor.from_user(u) for u in users), key=lambda a: a.display_name.lower()
        )
    )


@router.delete("/{campaign_id}/editing", status_code=status.HTTP_204_NO_CONTENT)
async def stop_editing(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> None:
    """Forgiving by design — called on unmount, must never become a failure."""
    await db.execute(
        delete(CampaignEditSession).where(
            CampaignEditSession.campaign_id == campaign_id,
            CampaignEditSession.user_id == caller.id,
        )
    )
    await db.commit()

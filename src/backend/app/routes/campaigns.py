"""Campaign drafts: a Content Manager builds a programme before anyone sees it.

Two rules shape every route here. First, a campaign belongs to the people
working on it: anyone else gets a 404, never a 403, so another team's
programmes cannot even be confirmed to exist. Second, naming a person is an
Administrator's act, as it is for assignments — a Content Manager picks
groups from the counts-only `GET /api/content/groups`.

A draft is inert: nothing here makes a campaign visible to a learner or sends
an email. That arrives with activation.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import is_administrator
from app.db import get_db
from app.dependencies import require_content_manager
from app.models import (
    Campaign,
    CampaignModule,
    CampaignTarget,
    Group,
    Module,
    ModuleTranslationGroup,
    User,
)
from app.schemas.campaigns import (
    CampaignCreateRequest,
    CampaignModuleInput,
    CampaignModuleResponse,
    CampaignResponse,
    CampaignSummaryResponse,
    CampaignTargetInput,
    CampaignTargetResponse,
    CampaignUpdateRequest,
    ModuleAvailability,
)
from app.schemas.modules import ModuleActor
from app.security.audit import record_audit_log

router = APIRouter(prefix="/api/content/campaigns", tags=["campaigns"])



def _campaign_not_found() -> HTTPException:
    # A fresh instance per miss: a shared one would accumulate tracebacks.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")


def may_see_campaign(user: User, campaign: Campaign) -> bool:
    """The one answer to "does this campaign exist for this caller?".

    Today: the creator. Collaborators and Administrators widen it in later
    tickets, and every route asks here, so it widens everywhere at once.
    """
    return campaign.created_by == user.id


def visible_campaigns_clause(user: User) -> ColumnElement[bool]:
    """`may_see_campaign` as a WHERE clause, for list queries. Keep the two in step."""
    return Campaign.created_by == user.id


async def _get_campaign_or_404(db: AsyncSession, campaign_id: uuid.UUID, caller: User) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or not may_see_campaign(caller, campaign):
        raise _campaign_not_found()
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
    """The campaigns this caller may see — only the ones they created, for now."""
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

"""Campaign lifecycle and what a campaign means to a learner.

Everything a learner can do through a campaign is derived live, on every read,
from `campaign_targets` against their *current* group membership and from
`module_progress` — nothing is copied or stored. That is what makes a late
joiner see a campaign, a leaver lose it while keeping what they finished, and a
substantive republish reopen a completed campaign without anyone writing to it.

Shared by the authoring routes (activate/close), the learner routes ("my
learning", module access, asset delivery) and the daily job (start-date
activation).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments import resolve_target_users
from app.core.config import get_settings
from app.models import (
    Campaign,
    CampaignModule,
    CampaignTarget,
    Module,
    ModuleProgress,
    ModuleTranslationGroup,
    User,
)
from app.security.audit import record_audit_log
from app.security.mailer import SESClient, send_campaign_activation_email
from app.security.system_settings import deployment_today

logger = logging.getLogger("traindrain.campaigns")


# --- Who a campaign reaches ---------------------------------------------------


def _targets_user(user: User):  # noqa: ANN202 - a SQLAlchemy clause
    conditions = [
        and_(CampaignTarget.target_type == "user", CampaignTarget.target_id == user.id)
    ]
    group_ids = [group.id for group in user.groups]
    if group_ids:
        conditions.append(
            and_(CampaignTarget.target_type == "group", CampaignTarget.target_id.in_(group_ids))
        )
    return or_(*conditions)


async def campaigns_targeting(
    db: AsyncSession, user: User, *, statuses: tuple[str, ...]
) -> list[Campaign]:
    """Campaigns in one of `statuses` that name this user, directly or through
    a group they belong to right now."""
    return list(
        (
            await db.execute(
                select(Campaign)
                .join(CampaignTarget, CampaignTarget.campaign_id == Campaign.id)
                .where(Campaign.status.in_(statuses), _targets_user(user))
                .distinct()
            )
        )
        .scalars()
        .unique()
    )


async def campaign_translation_group_ids(db: AsyncSession, user: User) -> frozenset[uuid.UUID]:
    """The material this user may read *through a campaign*, right now.

    Active campaigns open all of their modules. A closed campaign opens only
    what the learner had already started: closing stops new starts but keeps
    every record readable. Cheap on purpose — `may_read_module` needs this on
    every request.
    """
    active = await campaigns_targeting(db, user, statuses=("active",))
    closed = await campaigns_targeting(db, user, statuses=("closed",))

    group_ids = {row.translation_group_id for c in active for row in c.modules}
    closed_ids = {row.translation_group_id for c in closed for row in c.modules}
    if closed_ids:
        started = (
            await db.execute(
                select(ModuleProgress.translation_group_id).where(
                    ModuleProgress.user_id == user.id,
                    ModuleProgress.translation_group_id.in_(closed_ids),
                )
            )
        ).scalars()
        group_ids |= set(started)
    return frozenset(group_ids)


async def resolve_campaign_audience(db: AsyncSession, campaign: Campaign) -> list[User]:
    """Every currently-targeted, still-active learner, once each."""
    seen: dict[uuid.UUID, User] = {}
    for target in campaign.targets:
        for user in await resolve_target_users(
            db, target_type=target.target_type, target_id=target.target_id
        ):
            if user.disabled_at is None and user.erased_at is None:
                seen.setdefault(user.id, user)
    return list(seen.values())


# --- Live completion ----------------------------------------------------------


def is_current_completion(progress: ModuleProgress | None) -> bool:
    """Complete *and* not superseded by a substantive republish."""
    return (
        progress is not None
        and progress.completed_at is not None
        and progress.superseded_at is None
    )


@dataclass(frozen=True)
class CampaignProgress:
    required_total: int
    required_done: int

    @property
    def complete(self) -> bool:
        """Every mandatory module done. A campaign with none has nothing to
        complete, so it never reads as complete."""
        return self.required_total > 0 and self.required_done == self.required_total


def compute_progress(
    modules: list[CampaignModule], progress: dict[uuid.UUID, ModuleProgress]
) -> CampaignProgress:
    """Computed on every read and never stored: a superseded completion stops
    counting the moment the publish marks it, with no campaign row to repair."""
    mandatory = [row for row in modules if row.requirement == "mandatory"]
    done = sum(
        1 for row in mandatory if is_current_completion(progress.get(row.translation_group_id))
    )
    return CampaignProgress(required_total=len(mandatory), required_done=done)


# --- Lifecycle ----------------------------------------------------------------


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message}
    )


async def activation_problems(db: AsyncSession, campaign: Campaign) -> dict[str, object]:
    """Why this campaign may not go live, or an empty dict if it may.

    Every mandatory module must have a published variant, and somebody must be
    targeted — otherwise activation would promise learners something they
    cannot open, or nobody anything.
    """
    problems: dict[str, object] = {}
    mandatory = [row.translation_group_id for row in campaign.modules if row.requirement == "mandatory"]
    if mandatory:
        published = set(
            (
                await db.execute(
                    select(Module.translation_group_id).where(
                        Module.translation_group_id.in_(mandatory),
                        Module.status == "published",
                        Module.current_version_id.is_not(None),
                    )
                )
            ).scalars()
        )
        unpublished = [str(g) for g in mandatory if g not in published]
        if unpublished:
            problems["unpublished_modules"] = unpublished
    if not campaign.targets:
        problems["no_targets"] = True
    return problems


async def activate_campaign(
    db: AsyncSession, ses_client: SESClient, campaign: Campaign, *, actor_id: uuid.UUID,
    trigger: str = "manual",
) -> int:
    """draft → active, then one email per currently-targeted learner.

    Returns how many were emailed. Does not commit: the caller owns the
    transaction, so a failed send leaves no half-activated campaign behind.
    Learners who join a targeted group later are not emailed retroactively —
    the audience is resolved here, once.
    """
    # Re-read under a row lock: two concurrent activations (or a manual one
    # racing the daily job) must not both see "draft" and both email everyone.
    await db.refresh(campaign, with_for_update=True)
    if campaign.status != "draft":
        raise _conflict(
            "invalid_transition", f"A {campaign.status} campaign cannot be activated."
        )
    problems = await activation_problems(db, campaign)
    if problems:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "campaign_not_activatable",
                "message": "Publish every mandatory module and add a target before activating.",
                **problems,
            },
        )

    campaign.status = "active"
    audience = await resolve_campaign_audience(db, campaign)
    await record_audit_log(
        db,
        actor_user_id=actor_id,
        action="campaign_activated",
        detail={
            "campaign_id": str(campaign.id),
            "name": campaign.name,
            "trigger": trigger,
            "learners_notified": len(audience),
        },
    )
    url = f"{get_settings().frontend_base_url}/modules"
    for learner in audience:
        await send_campaign_activation_email(
            ses_client,
            to_email=learner.email,
            language=learner.preferred_language or "en",
            campaign_name=campaign.name,
            due_date=campaign.due_date,
            url=url,
        )
    return len(audience)


async def close_campaign(db: AsyncSession, campaign: Campaign, *, actor_id: uuid.UUID) -> None:
    """active → closed. Progress and records stay; new starts and reminders stop."""
    if campaign.status != "active":
        raise _conflict("invalid_transition", f"A {campaign.status} campaign cannot be closed.")
    campaign.status = "closed"
    await record_audit_log(
        db,
        actor_user_id=actor_id,
        action="campaign_closed",
        detail={"campaign_id": str(campaign.id), "name": campaign.name},
    )


async def suspend_campaign(db: AsyncSession, campaign: Campaign, *, actor_id: uuid.UUID) -> None:
    """active → suspended. Withdraws only the campaign's own route to its modules
    (`campaign_translation_group_ids` looks at active and closed campaigns, so a
    suspended one contributes nothing); progress rows are untouched, and a
    direct assignment or the open catalog still reaches a module as before."""
    await db.refresh(campaign, with_for_update=True)
    if campaign.status != "active":
        raise _conflict("invalid_transition", f"A {campaign.status} campaign cannot be suspended.")
    campaign.status = "suspended"
    await record_audit_log(
        db,
        actor_user_id=actor_id,
        action="campaign_suspended",
        detail={"campaign_id": str(campaign.id), "name": campaign.name},
    )


async def resume_campaign(db: AsyncSession, campaign: Campaign, *, actor_id: uuid.UUID) -> None:
    """suspended → active. Due dates never shift on their own: a campaign
    resumed past its due date succeeds but is flagged `due_date_lapsed` until an
    author sets a later date."""
    await db.refresh(campaign, with_for_update=True)
    if campaign.status != "suspended":
        raise _conflict("invalid_transition", f"A {campaign.status} campaign cannot be resumed.")
    today = await deployment_today(db)
    lapsed = campaign.due_date is not None and campaign.due_date < today
    campaign.status = "active"
    campaign.due_date_lapsed = lapsed
    await record_audit_log(
        db,
        actor_user_id=actor_id,
        action="campaign_resumed",
        detail={
            "campaign_id": str(campaign.id),
            "name": campaign.name,
            "due_date_lapsed": lapsed,
        },
    )


async def suspended_translation_group_ids(db: AsyncSession, user: User) -> frozenset[uuid.UUID]:
    """Material this user is targeted for only through a suspended campaign — used
    to keep it out of "my learning" while no other route reaches it."""
    suspended = await campaigns_targeting(db, user, statuses=("suspended",))
    return frozenset(row.translation_group_id for c in suspended for row in c.modules)


async def activate_due_campaigns(
    db: AsyncSession, ses_client: SESClient, *, today: date | None = None
) -> int:
    """The daily job's half: draft campaigns whose start date has arrived go live.

    Idempotent because the status flip is the guard — a second run finds
    nothing in `draft` to touch. A campaign that cannot be activated yet (an
    unpublished mandatory module, no targets) is left in draft and tried again
    tomorrow; one campaign's failure never blocks the others. Commits per
    campaign, so a mail failure rolls back only that campaign's activation.
    """
    today = today or await deployment_today(db)
    due = list(
        (
            await db.execute(
                select(Campaign).where(
                    Campaign.status == "draft",
                    Campaign.start_date.is_not(None),
                    Campaign.start_date <= today,
                )
            )
        )
        .scalars()
        .unique()
    )
    activated = 0
    for campaign in due:
        try:
            if await activation_problems(db, campaign):
                logger.info("Campaign %s is not ready to activate; will retry.", campaign.id)
                continue
            await activate_campaign(
                db, ses_client, campaign, actor_id=campaign.created_by, trigger="start_date"
            )
            await db.commit()
            activated += 1
        except Exception:
            await db.rollback()
            logger.exception("Could not activate campaign %s.", campaign.id)
    return activated


async def primary_variant_titles(
    db: AsyncSession, group_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Fallback title for a group with no published variant — a draft's or a
    tombstone's — so a campaign row never renders blank."""
    if not group_ids:
        return {}
    titles: dict[uuid.UUID, str] = {}
    groups = (
        await db.execute(
            select(ModuleTranslationGroup).where(ModuleTranslationGroup.id.in_(group_ids))
        )
    ).scalars()
    primaries = {g.id: g.primary_module_id for g in groups}
    modules = (
        await db.execute(select(Module).where(Module.translation_group_id.in_(group_ids)))
    ).scalars()
    by_group: dict[uuid.UUID, list[Module]] = {}
    for module in modules:
        by_group.setdefault(module.translation_group_id, []).append(module)
    for group_id, variants in by_group.items():
        chosen = next((m for m in variants if m.id == primaries.get(group_id)), variants[0])
        titles[group_id] = chosen.title
    return titles

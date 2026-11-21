"""Did people do the training? Two different answers for two different roles.

A Content Manager sees aggregate counts per targeted **group** — never a name,
because authoring content must not require directory access, the same
data-minimization boundary `app.routes.assignments` draws. An Administrator
sees exactly who has and has not completed, across every assignment on the
material (group or individual).

Both walk the same underlying facts: every `Assignment` targeting a
translation group, each target's current membership (`resolve_target_users`,
resolved live rather than expanded and stored — see `Assignment`'s own
docstring), and each targeted learner's `ModuleProgress` row. Counted over the
whole translation group rather than one language variant, because that is
what a `ModuleProgress` row is keyed on: one person reading one body of
material, whichever language they happened to open (ticket 6).
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments import is_overdue, nearer_due_date, resolve_target_users
from app.models import (
    Assignment,
    Campaign,
    CampaignModule,
    Group,
    ModuleProgress,
    QuizAttempt,
    User,
)

LearnerState = Literal["completed", "in_progress", "not_started"]


@dataclass(frozen=True)
class LearnerStanding:
    """Where one targeted learner stands against one body of material.

    A completed-but-superseded learner is reported as `in_progress`, never as
    `completed` — a substantive republish is exactly the event that makes their
    prior attestation no longer current (`_send_learners_back` in
    `app.routes.content`) — but `completed_at` and `completed_version_number`
    are carried anyway, unerased, so the roster can still say what they read
    and when even while showing them as outstanding now.
    """

    user: User
    state: LearnerState
    overdue: bool
    due_date: date | None
    completed_at: datetime | None
    completed_version_number: int | None


def _standing(
    user: User, progress: ModuleProgress | None, *, due_date: date | None, today: date
) -> LearnerStanding:
    completed = (
        progress is not None
        and progress.completed_at is not None
        and progress.superseded_at is None
    )
    state: LearnerState = "not_started"
    if completed:
        state = "completed"
    elif progress is not None:
        state = "in_progress"
    return LearnerStanding(
        user=user,
        state=state,
        overdue=is_overdue(due_date, completed=completed, today=today),
        due_date=due_date,
        completed_at=progress.completed_at if progress else None,
        completed_version_number=progress.completed_version_number if progress else None,
    )


def _live(users: Collection[User]) -> list[User]:
    """Members worth reporting on — not someone erased or disabled, the same
    filter assignment notification and reminders already apply to "who is
    really targeted right now"."""
    return [user for user in users if user.disabled_at is None and user.erased_at is None]


async def _progress_by_user(
    db: AsyncSession, translation_group_id: uuid.UUID, user_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, ModuleProgress]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(ModuleProgress).where(
                ModuleProgress.translation_group_id == translation_group_id,
                ModuleProgress.user_id.in_(user_ids),
            )
        )
    ).scalars()
    return {row.user_id: row for row in rows}


async def group_standings(
    db: AsyncSession, translation_group_id: uuid.UUID, *, today: date
) -> list[tuple[Group, list[LearnerStanding]]]:
    """Every group this material is assigned to, and how its members stand.

    Scoped to group-type assignments only. An individually-targeted learner
    (Administrator-only — see `Assignment`) never appears here: a Content
    Manager's aggregate must not turn into a one-person aggregate that
    identifies them by elimination.
    """
    assignments = (
        await db.execute(
            select(Assignment).where(
                Assignment.translation_group_id == translation_group_id,
                Assignment.target_type == "group",
            )
        )
    ).scalars()

    summaries: list[tuple[Group, list[LearnerStanding]]] = []
    for assignment in assignments:
        group = await db.get(Group, assignment.target_id)
        if group is None:
            continue
        members = _live(
            await resolve_target_users(db, target_type="group", target_id=assignment.target_id)
        )
        progress = await _progress_by_user(db, translation_group_id, [m.id for m in members])
        standings = [
            _standing(member, progress.get(member.id), due_date=assignment.due_date, today=today)
            for member in members
        ]
        summaries.append((group, standings))
    return summaries


async def full_roster(
    db: AsyncSession,
    translation_group_id: uuid.UUID,
    *,
    today: date,
    include_unassigned_progress: bool = False,
    include_quiz_attempters: bool = False,
) -> list[LearnerStanding]:
    """Every learner targeted by any assignment on this material — group or
    individual — deduplicated, with the nearest due date across whatever
    assignment(s) name them (the same tie-break `app.assignments` applies from
    a single learner's side).

    `include_unassigned_progress` additionally includes anyone with a
    `ModuleProgress` row here who no assignment currently names — with no due
    date, since none targets them. Ticket 11's module delete removes every
    assignment on the material it tombstones, and without this a deleted
    module's roster would go empty the moment its evidence became relevant:
    "who did this training" has to stay answerable from what people actually
    read, not only from who is still being asked to. Left off by default so a
    live module's report keeps meaning exactly what it always has — the
    audience it is currently targeting.
    """
    assignments = (
        await db.execute(select(Assignment).where(Assignment.translation_group_id == translation_group_id))
    ).scalars()

    users: dict[uuid.UUID, User] = {}
    due_dates: dict[uuid.UUID, date | None] = {}
    for assignment in assignments:
        for member in _live(
            await resolve_target_users(
                db, target_type=assignment.target_type, target_id=assignment.target_id
            )
        ):
            if member.id not in users or nearer_due_date(assignment.due_date, due_dates[member.id]):
                due_dates[member.id] = assignment.due_date
            users[member.id] = member

    if include_unassigned_progress:
        progress_rows = (
            await db.execute(
                select(ModuleProgress).where(
                    ModuleProgress.translation_group_id == translation_group_id
                )
            )
        ).scalars()
        unassigned_ids = {row.user_id for row in progress_rows} - set(users)
        if unassigned_ids:
            for member in _live(
                (
                    await db.execute(select(User).where(User.id.in_(unassigned_ids)))
                ).scalars()
            ):
                users[member.id] = member
                due_dates[member.id] = None

    if include_quiz_attempters:
        # Someone who reached the quiz through the open catalog is named by no
        # assignment, yet is exactly who an Administrator may need to reset.
        attempter_ids = set(
            (
                await db.execute(
                    select(QuizAttempt.user_id)
                    .where(QuizAttempt.translation_group_id == translation_group_id)
                    .distinct()
                )
            ).scalars()
        ) - set(users)
        if attempter_ids:
            for member in _live(
                (await db.execute(select(User).where(User.id.in_(attempter_ids)))).scalars()
            ):
                users[member.id] = member
                due_dates[member.id] = None

    progress = await _progress_by_user(db, translation_group_id, users.keys())
    return [
        _standing(user, progress.get(user_id), due_date=due_dates[user_id], today=today)
        for user_id, user in users.items()
    ]


# --- Campaign reports ---------------------------------------------------------
#
# The same privacy split as the module report, over a campaign. Everything is
# computed live from `module_progress` through the one completion notion
# (`is_current_completion`) the learner's own view and the sequential lock use,
# so a superseded completion reports as outstanding while its prior record
# stays visible to Administrators.

CampaignLearnerState = Literal["completed", "in_progress", "not_started", "suspended"]
ModuleCellState = Literal["completed", "in_progress", "not_started"]


@dataclass(frozen=True)
class CampaignModuleCell:
    """One learner's standing on one campaign module (Administrator roster)."""

    translation_group_id: uuid.UUID
    requirement: str
    state: ModuleCellState
    unavailable: bool
    completed_at: datetime | None
    completed_version_number: int | None


@dataclass(frozen=True)
class CampaignLearnerStanding:
    """Where one targeted learner stands against a whole campaign.

    `suspended` replaces `in_progress`/`not_started` for anyone who has not
    completed while the campaign is suspended — the learner cannot act, so
    neither "behind" nor "waiting" is honest — and `overdue` is frozen false
    then, as it is on the learner's own view. `progress_percent` is mandatory
    modules currently complete over mandatory modules required (0 when none).
    """

    user: User
    state: CampaignLearnerState
    overdue: bool
    required_total: int
    required_done: int
    progress_percent: int
    cells: list[CampaignModuleCell]


async def _campaign_context(
    db: AsyncSession, campaign: Campaign
) -> tuple[frozenset[uuid.UUID], list[CampaignModule]]:
    from app.campaigns import deleted_group_ids

    modules = sorted(campaign.modules, key=lambda row: row.position)
    deleted = await deleted_group_ids(db, [row.translation_group_id for row in modules])
    return deleted, modules


def _campaign_standing(
    user: User,
    campaign: Campaign,
    modules: list[CampaignModule],
    deleted: Collection[uuid.UUID],
    progress: dict[uuid.UUID, ModuleProgress],
    *,
    today: date,
) -> CampaignLearnerStanding:
    from app.campaigns import compute_progress, is_current_completion

    summary = compute_progress(modules, progress, deleted)
    touched = any(row.translation_group_id in progress for row in modules)
    state: CampaignLearnerState
    if summary.complete:
        state = "completed"
    elif campaign.status == "suspended":
        state = "suspended"
    else:
        state = "in_progress" if touched else "not_started"
    cells = []
    for row in modules:
        row_progress = progress.get(row.translation_group_id)
        done = is_current_completion(row_progress)
        cells.append(
            CampaignModuleCell(
                translation_group_id=row.translation_group_id,
                requirement=row.requirement,
                state="completed" if done else ("in_progress" if row_progress else "not_started"),
                unavailable=row.translation_group_id in deleted,
                completed_at=row_progress.completed_at if row_progress else None,
                completed_version_number=(
                    row_progress.completed_version_number if row_progress else None
                ),
            )
        )
    percent = (
        round(100 * summary.required_done / summary.required_total) if summary.required_total else 0
    )
    return CampaignLearnerStanding(
        user=user,
        state=state,
        overdue=(
            campaign.status == "active"
            and not summary.complete
            and is_overdue(campaign.due_date, completed=False, today=today)
        ),
        required_total=summary.required_total,
        required_done=summary.required_done,
        progress_percent=percent,
        cells=cells,
    )


async def _campaign_progress(
    db: AsyncSession, modules: list[CampaignModule], user_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, dict[uuid.UUID, ModuleProgress]]:
    """user id -> translation group id -> progress, for the campaign's modules."""
    by_user: dict[uuid.UUID, dict[uuid.UUID, ModuleProgress]] = {}
    group_ids = [row.translation_group_id for row in modules]
    if not user_ids or not group_ids:
        return by_user
    rows = (
        await db.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id.in_(user_ids),
                ModuleProgress.translation_group_id.in_(group_ids),
            )
        )
    ).scalars()
    for row in rows:
        by_user.setdefault(row.user_id, {})[row.translation_group_id] = row
    return by_user


async def campaign_group_standings(
    db: AsyncSession, campaign: Campaign, *, today: date
) -> list[tuple[Group, list[CampaignLearnerStanding]]]:
    """Each targeted group and how its live members stand — group targets only,
    so an individually-targeted learner never becomes a one-person aggregate."""
    deleted, modules = await _campaign_context(db, campaign)
    summaries: list[tuple[Group, list[CampaignLearnerStanding]]] = []
    for target in campaign.targets:
        if target.target_type != "group":
            continue
        group = await db.get(Group, target.target_id)
        if group is None:
            continue
        members = _live(
            await resolve_target_users(db, target_type="group", target_id=target.target_id)
        )
        progress = await _campaign_progress(db, modules, [m.id for m in members])
        summaries.append(
            (
                group,
                [
                    _campaign_standing(
                        m, campaign, modules, deleted, progress.get(m.id, {}), today=today
                    )
                    for m in members
                ],
            )
        )
    return summaries


async def campaign_full_roster(
    db: AsyncSession, campaign: Campaign, *, today: date
) -> list[CampaignLearnerStanding]:
    """Every currently-targeted learner, group or individual, once each."""
    from app.campaigns import resolve_campaign_audience

    deleted, modules = await _campaign_context(db, campaign)
    audience = await resolve_campaign_audience(db, campaign)
    progress = await _campaign_progress(db, modules, [u.id for u in audience])
    return [
        _campaign_standing(u, campaign, modules, deleted, progress.get(u.id, {}), today=today)
        for u in audience
    ]

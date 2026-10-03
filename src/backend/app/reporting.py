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
from app.models import Assignment, Group, ModuleProgress, User

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

    progress = await _progress_by_user(db, translation_group_id, users.keys())
    return [
        _standing(user, progress.get(user_id), due_date=due_dates[user_id], today=today)
        for user_id, user in users.items()
    ]

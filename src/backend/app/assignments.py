"""Resolving what a learner is assigned to read.

Shared by the learner routes (what `may_read_module` admits, and what shows up
on "my learning") and asset delivery (the same admission has to reach an image
inside an assigned module, not only its pages).

One query per request, not a lookup per module: a caller builds the audience
once at the top of a request and asks it — never inside a loop over modules.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Assignment, Group, User, group_members


def _target_conditions(user: User) -> list[ColumnElement[bool]]:
    """Every assignment that names this user, directly or through a group."""
    conditions: list[ColumnElement[bool]] = [
        and_(Assignment.target_type == "user", Assignment.target_id == user.id)
    ]
    group_ids = [group.id for group in user.groups]
    if group_ids:
        conditions.append(
            and_(Assignment.target_type == "group", Assignment.target_id.in_(group_ids))
        )
    return conditions


async def assigned_translation_group_ids(db: AsyncSession, user: User) -> frozenset[uuid.UUID]:
    """The bodies of material this user is assigned to read, right now.

    Cheap on purpose — this is the version `may_read_module` needs on every
    request, so it asks for nothing beyond the group ids themselves.
    """
    rows = await db.execute(
        select(Assignment.translation_group_id).where(or_(*_target_conditions(user)))
    )
    return frozenset(rows.scalars())


@dataclass(frozen=True)
class AssignedModule:
    """One body of material assigned to a learner, resolved down to what
    their own list needs: the nearer of any competing due dates, and the
    requirement that came with it."""

    translation_group_id: uuid.UUID
    due_date: date | None
    requirement: str
    auto_reminders: bool


def nearer_due_date(candidate: date | None, current: date | None) -> bool:
    """Does `candidate` win the "nearest due date" tie-break over `current`?

    A due date beats no due date — a defined deadline is more urgent than
    material with none — and between two defined dates, the earlier one wins.
    Shared with `app.reporting`, which resolves the same tie-break the other
    way round: one learner's nearest date across many assignments there,
    many learners' own nearest dates here.
    """
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate < current


async def assignments_for_user(
    db: AsyncSession, user: User
) -> dict[uuid.UUID, AssignedModule]:
    """Every body of material assigned to this user, one entry per translation
    group, with the nearest due date winning when more than one assignment
    (a direct one and a group one, or two groups) covers the same material.
    """
    rows = (
        await db.execute(select(Assignment).where(or_(*_target_conditions(user))))
    ).scalars()

    winners: dict[uuid.UUID, Assignment] = {}
    for row in rows:
        current = winners.get(row.translation_group_id)
        if current is None or nearer_due_date(row.due_date, current.due_date):
            winners[row.translation_group_id] = row

    return {
        group_id: AssignedModule(
            translation_group_id=group_id,
            due_date=assignment.due_date,
            requirement=assignment.requirement,
            auto_reminders=assignment.auto_reminders,
        )
        for group_id, assignment in winners.items()
    }


def is_overdue(due_date: date | None, *, completed: bool, today: date) -> bool:
    """Has this due date passed, for material not currently completed?

    A completed learner is never overdue, whatever the date says — the
    obligation the date was chasing has been met. `today` is never computed
    here: it comes from `app.security.system_settings.deployment_today`, the
    deployment-wide timezone setting ticket 8 introduced, so "overdue" means
    the same moment here as it does for the reminder job chasing the same
    due date.
    """
    if due_date is None or completed:
        return False
    return due_date < today


async def resolve_target_users(
    db: AsyncSession, *, target_type: str, target_id: uuid.UUID
) -> list[User]:
    """Who an assignment's target actually names, right now.

    Shared by assignment creation (the one-time notification email) and the
    reminder job (`app.reminders`) — both need "who is targeted today", never
    a membership list expanded and stored, per `Assignment`'s own docstring.
    """
    if target_type == "group":
        group = await db.get(Group, target_id)
        if group is None:
            return []
        return list(
            (
                await db.execute(
                    select(User)
                    .join(group_members, group_members.c.user_id == User.id)
                    .where(group_members.c.group_id == group.id)
                )
            ).scalars()
        )

    target_user = await db.get(User, target_id)
    if target_user is None or target_user.erased_at is not None:
        return []
    return [target_user]

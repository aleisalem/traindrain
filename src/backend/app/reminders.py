"""Chasing mandatory training without becoming noise.

Two paths write the same evidence row (`ModuleReminder`) for every email they
actually send: a daily scheduled cadence (`run_scheduled_reminders`, invoked
by `app.jobs.send_reminders`) and an Administrator's immediate nudge
(`send_manual_reminders`, behind `POST /api/content/modules/{id}/remind`).
Both consult that table before sending — it is what makes a second run of the
job on the same day a no-op, and what the one-email-per-learner-per-module-
per-day cap is checked against. The manual endpoint's *own*, coarser
once-per-module-per-day rate limit is a separate check the route makes
against its `reminder_sent` audit entry instead (see
`app.routes.assignments._manual_nudge_already_invoked_today`), because that
entry is written on every successful call — including one that reaches
nobody — while a `ModuleReminder` row only exists when an email actually
went out.

Only mandatory assignments with `auto_reminders` on and a due date set are
ever reminded automatically — a recommendation was never a deadline, and a
cadence has nothing to count down to without a date. The manual nudge targets
the exact same audience, an explicit "run it now" rather than a broader blast.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments import resolve_target_users
from app.core.config import get_settings
from app.models import (
    Assignment,
    Module,
    ModuleProgress,
    ModuleReminder,
    ModuleTranslationGroup,
    User,
)
from app.security.mailer import SESClient, send_reminder_email
from app.security.system_settings import get_reminder_timezone

KIND_ADVANCE_7 = "advance_7"
KIND_ADVANCE_1 = "advance_1"
KIND_DUE = "due"
KIND_OVERDUE_WEEKLY = "overdue_weekly"
KIND_MANUAL = "manual"

_AUTO_REMINDER_ELIGIBLE = (
    Assignment.requirement == "mandatory",
    Assignment.auto_reminders.is_(True),
    Assignment.due_date.is_not(None),
)


def scheduled_kind_for_due_date(due_date: date, today: date) -> str | None:
    """Which cadence checkpoint, if any, today lands on for this due date.

    7 days before, 1 day before, on the day, then weekly for as long as it
    stays overdue. `delta % 7 == 0` also catches the negative multiples
    Python's modulo gives for an overdue delta (-7, -14, …), so no separate
    sign-handling is needed for the weekly leg.
    """
    delta = (due_date - today).days
    if delta == 7:
        return KIND_ADVANCE_7
    if delta == 1:
        return KIND_ADVANCE_1
    if delta == 0:
        return KIND_DUE
    if delta < 0 and delta % 7 == 0:
        return KIND_OVERDUE_WEEKLY
    return None


@dataclass(frozen=True)
class ReminderWindow:
    """"Today" in the deployment timezone, and the instants it spans.

    The three always travel together — every "already reminded today" /
    "already invoked today" check compares a timestamp against `start`/`end`,
    so a reminder sent at 23:50 local time and a check made the next minute
    agree on which day it belongs to (a plain UTC date comparison would not,
    worst-case by a whole day).
    """

    today: date
    start: datetime
    end: datetime


async def deployment_day_bounds(db: AsyncSession) -> ReminderWindow:
    tz_name = await get_reminder_timezone(db)
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    return ReminderWindow(today=today, start=start, end=start + timedelta(days=1))


async def _module_for_notification(db: AsyncSession, translation_group_id: uuid.UUID) -> Module | None:
    """A published module to put a title and a language on the email.

    The group's primary variant if it is published, else any published
    variant — deterministic, so two reminders about the same material agree.
    Unpublished or deleted material has nothing to remind anyone to read.
    """
    group = await db.get(ModuleTranslationGroup, translation_group_id)
    if group is not None and group.primary_module_id is not None:
        primary = await db.get(Module, group.primary_module_id)
        if primary is not None and primary.status == "published":
            return primary
    result = await db.execute(
        select(Module)
        .where(Module.translation_group_id == translation_group_id, Module.status == "published")
        .order_by(Module.language)
    )
    return result.scalars().first()


async def _is_current_completion(
    db: AsyncSession, *, user_id: uuid.UUID, translation_group_id: uuid.UUID
) -> bool:
    progress = await db.scalar(
        select(ModuleProgress).where(
            ModuleProgress.user_id == user_id,
            ModuleProgress.translation_group_id == translation_group_id,
        )
    )
    return progress is not None and progress.completed_at is not None and progress.superseded_at is None


async def _already_reminded_today(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    translation_group_id: uuid.UUID,
    day_start: datetime,
    day_end: datetime,
) -> bool:
    """The one-per-learner-per-module-per-day cap, checked across every kind
    and every assignment that targets this translation group — a group
    assignment and an individual one covering the same learner must still
    only ever reach them once today.
    """
    count = await db.scalar(
        select(func.count())
        .select_from(ModuleReminder)
        .join(Assignment, Assignment.id == ModuleReminder.assignment_id)
        .where(
            Assignment.translation_group_id == translation_group_id,
            ModuleReminder.user_id == user_id,
            ModuleReminder.sent_at >= day_start,
            ModuleReminder.sent_at < day_end,
        )
    )
    return bool(count)


async def _send_one_reminder(
    db: AsyncSession,
    ses_client: SESClient,
    *,
    assignment: Assignment,
    learner: User,
    module: Module,
    kind: str,
) -> None:
    module_url = f"{get_settings().frontend_base_url}/modules/{assignment.translation_group_id}"
    await send_reminder_email(
        ses_client,
        to_email=learner.email,
        language=learner.preferred_language or "en",
        module_title=module.title,
        due_date=assignment.due_date,
        module_url=module_url,
        kind=kind,
    )
    db.add(ModuleReminder(assignment_id=assignment.id, user_id=learner.id, kind=kind))
    await db.flush()


async def _eligible_assignments(
    db: AsyncSession, *, translation_group_id: uuid.UUID | None = None
) -> list[Assignment]:
    conditions = list(_AUTO_REMINDER_ELIGIBLE)
    if translation_group_id is not None:
        conditions.append(Assignment.translation_group_id == translation_group_id)
    return list((await db.execute(select(Assignment).where(*conditions))).scalars())


async def run_scheduled_reminders(db: AsyncSession, ses_client: SESClient) -> int:
    """The daily job: every mandatory, auto-reminded assignment that lands on
    a cadence checkpoint today gets its outstanding learners emailed once.

    Does not commit — the caller (`app.jobs.send_reminders`) owns that, the
    same convention every route here follows.
    """
    window = await deployment_day_bounds(db)
    sent_count = 0
    for assignment in await _eligible_assignments(db):
        assert assignment.due_date is not None  # enforced by _AUTO_REMINDER_ELIGIBLE
        kind = scheduled_kind_for_due_date(assignment.due_date, window.today)
        if kind is None:
            continue
        module = await _module_for_notification(db, assignment.translation_group_id)
        if module is None:
            continue
        for learner in await resolve_target_users(
            db, target_type=assignment.target_type, target_id=assignment.target_id
        ):
            if learner.disabled_at is not None or learner.erased_at is not None:
                continue
            if await _is_current_completion(
                db, user_id=learner.id, translation_group_id=assignment.translation_group_id
            ):
                continue
            if await _already_reminded_today(
                db,
                user_id=learner.id,
                translation_group_id=assignment.translation_group_id,
                day_start=window.start,
                day_end=window.end,
            ):
                continue
            await _send_one_reminder(
                db, ses_client, assignment=assignment, learner=learner, module=module, kind=kind
            )
            sent_count += 1
    return sent_count


async def send_manual_reminders(
    db: AsyncSession, ses_client: SESClient, *, translation_group_id: uuid.UUID
) -> int:
    """An Administrator's immediate nudge for one module's material.

    Same audience the scheduled cadence would reach — mandatory, auto-
    reminded, due-dated assignments — rather than every assignment ever made
    against this material, so a nudge never reaches someone whose author
    deliberately left reminders off. The per-learner daily cap still applies:
    someone the scheduled job already reached today is skipped here too.

    Does not commit, and does not itself enforce the once-per-module-per-day
    rate limit on the *action* — the route checks that first (against the
    `reminder_sent` audit entry, which it writes on every call regardless of
    how many learners this function reaches), so a refused call never
    reaches this far.
    """
    module = await _module_for_notification(db, translation_group_id)
    if module is None:
        return 0
    window = await deployment_day_bounds(db)

    sent_count = 0
    already_reminded: set[uuid.UUID] = set()
    for assignment in await _eligible_assignments(db, translation_group_id=translation_group_id):
        for learner in await resolve_target_users(
            db, target_type=assignment.target_type, target_id=assignment.target_id
        ):
            if learner.id in already_reminded:
                continue
            if learner.disabled_at is not None or learner.erased_at is not None:
                continue
            if await _is_current_completion(
                db, user_id=learner.id, translation_group_id=translation_group_id
            ):
                continue
            if await _already_reminded_today(
                db,
                user_id=learner.id,
                translation_group_id=translation_group_id,
                day_start=window.start,
                day_end=window.end,
            ):
                continue
            await _send_one_reminder(
                db, ses_client, assignment=assignment, learner=learner, module=module, kind=KIND_MANUAL
            )
            already_reminded.add(learner.id)
            sent_count += 1
    return sent_count

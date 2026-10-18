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
from app.campaigns import deleted_group_ids, is_current_completion, resolve_campaign_audience
from app.core.config import get_settings
from app.models import (
    Assignment,
    Campaign,
    CampaignReminder,
    Module,
    ModuleProgress,
    ModuleReminder,
    ModuleTranslationGroup,
    User,
)
from app.security.mailer import SESClient, send_campaign_reminder_email, send_reminder_email
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
    if count:
        return True
    # A campaign email that already listed this module today covers it: the
    # learner is chased once, not once by the campaign and again by the module.
    covered = await db.scalar(
        select(func.count())
        .select_from(CampaignReminder)
        .where(
            CampaignReminder.user_id == user_id,
            CampaignReminder.translation_group_ids.contains([translation_group_id]),
            CampaignReminder.sent_at >= day_start,
            CampaignReminder.sent_at < day_end,
        )
    )
    return bool(covered)


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


# --- Campaign reminders ---------------------------------------------------------
#
# A learner is chased once per campaign, not once per module: one email that
# lists every mandatory module they still owe. It writes `CampaignReminder`
# rows, which the module path above consults (so a module the campaign email
# already covered today is not chased again) and which this path checks
# against the module path's `ModuleReminder` rows in turn (so a module
# already chased today is left off the campaign email). Whichever runs first
# the same day, the learner is reached once for any given module.


def _campaign_reminder_eligible(campaign: Campaign) -> bool:
    """Active, auto-reminded and dated. A suspended or closed campaign sends
    nothing; a resumed one needs no special case, since the cadence matches
    exact days and so never produces a catch-up burst for the days missed."""
    return (
        campaign.status == "active"
        and campaign.auto_reminders
        and campaign.due_date is not None
    )


async def _send_campaign_reminders(
    db: AsyncSession, ses_client: SESClient, campaign: Campaign, *, kind: str, window: ReminderWindow
) -> int:
    # Material nobody can read (no published variant) or that was deleted
    # elsewhere is not "owed", mirroring how campaign progress counts it.
    mandatory = [row.translation_group_id for row in campaign.modules if row.requirement == "mandatory"]
    mandatory = list(dict.fromkeys(mandatory))
    gone = await deleted_group_ids(db, mandatory)
    titles: dict[uuid.UUID, str] = {}
    for group_id in mandatory:
        if group_id in gone:
            continue
        module = await _module_for_notification(db, group_id)
        if module is not None:
            titles[group_id] = module.title
    if not titles:
        return 0

    audience = await resolve_campaign_audience(db, campaign)
    if not audience:
        return 0
    user_ids = [u.id for u in audience]

    progress = {
        (row.user_id, row.translation_group_id): row
        for row in (
            await db.execute(
                select(ModuleProgress).where(
                    ModuleProgress.user_id.in_(user_ids),
                    ModuleProgress.translation_group_id.in_(list(titles)),
                )
            )
        ).scalars()
    }
    # Already chased today, by either path: the send log, read once.
    module_chased = set(
        (
            await db.execute(
                select(ModuleReminder.user_id, Assignment.translation_group_id)
                .join(Assignment, Assignment.id == ModuleReminder.assignment_id)
                .where(
                    ModuleReminder.user_id.in_(user_ids),
                    Assignment.translation_group_id.in_(list(titles)),
                    ModuleReminder.sent_at >= window.start,
                    ModuleReminder.sent_at < window.end,
                )
            )
        ).tuples()
    )
    campaign_chased_today = (
        await db.execute(
            select(CampaignReminder).where(
                CampaignReminder.user_id.in_(user_ids),
                CampaignReminder.sent_at >= window.start,
                CampaignReminder.sent_at < window.end,
            )
        )
    ).scalars()
    covered: dict[uuid.UUID, set[uuid.UUID]] = {}
    already_this_campaign: set[uuid.UUID] = set()
    for row in campaign_chased_today:
        covered.setdefault(row.user_id, set()).update(row.translation_group_ids)
        if row.campaign_id == campaign.id:
            already_this_campaign.add(row.user_id)

    url = f"{get_settings().frontend_base_url}/modules"
    sent = 0
    for learner in audience:
        if learner.id in already_this_campaign:
            continue
        owed = [
            group_id
            for group_id in titles
            if not is_current_completion(progress.get((learner.id, group_id)))
            and (learner.id, group_id) not in module_chased
            and group_id not in covered.get(learner.id, set())
        ]
        if not owed:
            continue
        await send_campaign_reminder_email(
            ses_client,
            to_email=learner.email,
            language=learner.preferred_language or "en",
            campaign_name=campaign.name,
            module_titles=[titles[g] for g in owed],
            due_date=campaign.due_date,
            url=url,
            kind=kind,
        )
        db.add(
            CampaignReminder(
                campaign_id=campaign.id, user_id=learner.id, kind=kind, translation_group_ids=owed
            )
        )
        await db.flush()
        sent += 1
    return sent


async def run_scheduled_campaign_reminders(db: AsyncSession, ses_client: SESClient) -> int:
    """The daily job's campaign half. Does not commit — the caller owns that."""
    window = await deployment_day_bounds(db)
    campaigns = (
        (
            await db.execute(
                select(Campaign).where(
                    Campaign.status == "active",
                    Campaign.auto_reminders.is_(True),
                    Campaign.due_date.is_not(None),
                )
            )
        )
        .scalars()
        .unique()
    )
    sent = 0
    for campaign in campaigns:
        assert campaign.due_date is not None  # enforced by the query
        kind = scheduled_kind_for_due_date(campaign.due_date, window.today)
        if kind is None:
            continue
        sent += await _send_campaign_reminders(db, ses_client, campaign, kind=kind, window=window)
    return sent


async def send_manual_campaign_reminders(
    db: AsyncSession, ses_client: SESClient, campaign: Campaign
) -> int:
    """An Administrator's immediate nudge for one campaign.

    Same audience the scheduled cadence would reach — an active, auto-
    reminded, due-dated campaign — and the same per-learner cap. Does not
    enforce its own once-per-campaign-per-day limit: the route checks that
    first, against the `reminder_sent` audit entry.
    """
    if not _campaign_reminder_eligible(campaign):
        return 0
    window = await deployment_day_bounds(db)
    return await _send_campaign_reminders(db, ses_client, campaign, kind=KIND_MANUAL, window=window)

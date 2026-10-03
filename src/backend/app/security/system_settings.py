from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemSetting

INVITE_EXPIRY_DAYS_KEY = "invite_expiry_days"
DEFAULT_INVITE_EXPIRY_DAYS = 7


async def get_invite_expiry_days(db: AsyncSession) -> int:
    setting = await db.get(SystemSetting, INVITE_EXPIRY_DAYS_KEY)
    return int(setting.value) if setting is not None else DEFAULT_INVITE_EXPIRY_DAYS


async def set_invite_expiry_days(db: AsyncSession, days: int) -> None:
    # Flushes but doesn't commit — same convention as record_audit_log,
    # leaving the caller's route in charge of the transaction boundary.
    setting = await db.get(SystemSetting, INVITE_EXPIRY_DAYS_KEY)
    if setting is None:
        db.add(SystemSetting(key=INVITE_EXPIRY_DAYS_KEY, value=str(days)))
    else:
        setting.value = str(days)
    await db.flush()


REMINDER_TIMEZONE_KEY = "reminder_timezone"
DEFAULT_REMINDER_TIMEZONE = "Europe/Berlin"


class InvalidTimezoneError(ValueError):
    """Raised when a caller tries to set a timezone the IANA database doesn't know."""


async def get_reminder_timezone(db: AsyncSession) -> str:
    """The deployment-wide timezone "today" is evaluated in.

    Governs both reminder cadence ("is a due date 7 days away today?") and
    `app.assignments.is_overdue` — one timezone, so a module due date reads
    as overdue at the same moment for a learner's own list as for the
    reminder that chases it.
    """
    setting = await db.get(SystemSetting, REMINDER_TIMEZONE_KEY)
    return setting.value if setting is not None else DEFAULT_REMINDER_TIMEZONE


async def set_reminder_timezone(db: AsyncSession, timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise InvalidTimezoneError(f"Unknown timezone: {timezone!r}") from exc
    setting = await db.get(SystemSetting, REMINDER_TIMEZONE_KEY)
    if setting is None:
        db.add(SystemSetting(key=REMINDER_TIMEZONE_KEY, value=timezone))
    else:
        setting.value = timezone
    await db.flush()


async def deployment_today(db: AsyncSession) -> date:
    """"Today", as the configured deployment timezone would call it right now."""
    tz_name = await get_reminder_timezone(db)
    return datetime.now(ZoneInfo(tz_name)).date()

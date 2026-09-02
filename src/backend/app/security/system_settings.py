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

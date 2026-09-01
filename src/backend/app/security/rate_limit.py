from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginAttempt

# A sliding window, not a hard lockout — attempts age out on their own rather
# than requiring an unlock action, so this can't itself be used to lock a
# known-email account out indefinitely.
MAX_ATTEMPTS = 10
WINDOW = timedelta(minutes=15)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def is_rate_limited(
    db: AsyncSession,
    *,
    email: str,
    ip_address: str,
    max_attempts: int = MAX_ATTEMPTS,
    window: timedelta = WINDOW,
) -> bool:
    window_start = datetime.now(UTC) - window
    count = await db.scalar(
        select(func.count()).where(
            LoginAttempt.email == _normalize_email(email),
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.created_at >= window_start,
        )
    )
    return (count or 0) >= max_attempts


async def record_failed_login_attempt(db: AsyncSession, *, email: str, ip_address: str) -> None:
    db.add(LoginAttempt(email=_normalize_email(email), ip_address=ip_address))
    await db.commit()

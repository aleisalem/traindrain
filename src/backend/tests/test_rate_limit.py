from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.security.rate_limit import is_rate_limited, record_failed_login_attempt


async def test_not_rate_limited_before_any_attempts(db_session: AsyncSession) -> None:
    assert (
        await is_rate_limited(
            db_session, email="fresh@example.com", ip_address="10.0.0.1", max_attempts=2
        )
        is False
    )


async def test_rate_limited_once_max_attempts_reached(db_session: AsyncSession) -> None:
    email, ip = "brute-force@example.com", "10.0.0.2"
    for _ in range(2):
        await record_failed_login_attempt(db_session, email=email, ip_address=ip)

    assert await is_rate_limited(db_session, email=email, ip_address=ip, max_attempts=2) is True


async def test_rate_limit_is_scoped_to_the_email_ip_pair(db_session: AsyncSession) -> None:
    email, ip = "scoped@example.com", "10.0.0.3"
    for _ in range(5):
        await record_failed_login_attempt(db_session, email=email, ip_address=ip)

    # Same email, different IP: not rate limited.
    assert (
        await is_rate_limited(db_session, email=email, ip_address="10.0.0.4", max_attempts=2)
        is False
    )
    # Different email, same IP: not rate limited.
    assert (
        await is_rate_limited(
            db_session, email="someone-else@example.com", ip_address=ip, max_attempts=2
        )
        is False
    )


async def test_attempts_outside_the_window_do_not_count(db_session: AsyncSession) -> None:
    email, ip = "aged-out@example.com", "10.0.0.5"
    for _ in range(5):
        await record_failed_login_attempt(db_session, email=email, ip_address=ip)

    limited = await is_rate_limited(
        db_session,
        email=email,
        ip_address=ip,
        max_attempts=2,
        window=timedelta(seconds=0),
    )

    assert limited is False


async def test_email_matching_is_case_insensitive(db_session: AsyncSession) -> None:
    ip = "10.0.0.6"
    for _ in range(2):
        await record_failed_login_attempt(db_session, email="Case@Example.com", ip_address=ip)

    assert (
        await is_rate_limited(db_session, email="case@example.com", ip_address=ip, max_attempts=2)
        is True
    )

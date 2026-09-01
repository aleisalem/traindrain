import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security.passwords import hash_password
from app.security.sessions import (
    IDLE_TIMEOUT,
    create_session,
    get_valid_session,
    revoke_other_sessions,
    revoke_session,
)


async def _make_user(db_session: AsyncSession, *, email: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("irrelevant-password-value"),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_session_returns_a_lookup_able_token(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="session-create@example.com")

    session, token = await create_session(db_session, user_id=user.id)

    assert session.user_id == user.id
    assert session.token_hash != token
    looked_up = await get_valid_session(db_session, token)
    assert looked_up is not None
    assert looked_up.id == session.id


async def test_get_valid_session_rejects_unknown_token(db_session: AsyncSession) -> None:
    assert await get_valid_session(db_session, "not-a-real-token") is None


async def test_get_valid_session_rejects_revoked_session(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="session-revoked@example.com")
    session, token = await create_session(db_session, user_id=user.id)

    await revoke_session(db_session, session)

    assert await get_valid_session(db_session, token) is None


async def test_get_valid_session_rejects_absolute_expiry(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="session-absolute-expiry@example.com")
    session, token = await create_session(db_session, user_id=user.id)
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert await get_valid_session(db_session, token) is None


async def test_get_valid_session_rejects_idle_expiry(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="session-idle-expiry@example.com")
    session, token = await create_session(db_session, user_id=user.id)
    session.last_active_at = datetime.now(UTC) - IDLE_TIMEOUT - timedelta(seconds=1)
    await db_session.commit()

    assert await get_valid_session(db_session, token) is None


async def test_get_valid_session_refreshes_idle_clock(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="session-touch@example.com")
    session, token = await create_session(db_session, user_id=user.id)
    stale_last_active = datetime.now(UTC) - timedelta(minutes=10)
    session.last_active_at = stale_last_active
    await db_session.commit()

    refreshed = await get_valid_session(db_session, token)

    assert refreshed is not None
    assert refreshed.last_active_at > stale_last_active


async def test_revoke_other_sessions_keeps_the_current_session_alive(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="session-revoke-others@example.com")
    current_session, current_token = await create_session(db_session, user_id=user.id)
    _other_session, other_token = await create_session(db_session, user_id=user.id)

    await revoke_other_sessions(db_session, user_id=user.id, keep_session_id=current_session.id)

    assert await get_valid_session(db_session, current_token) is not None
    assert await get_valid_session(db_session, other_token) is None

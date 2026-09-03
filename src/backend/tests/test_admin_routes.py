import uuid

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, RecoveryCode, Role, TwoFactorCredential, User
from app.security.passwords import hash_password
from app.security.sessions import CHALLENGE_COOKIE_NAME, COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(db_session: AsyncSession, *, email: str, role_name: str) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        roles=[role],
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client: AsyncClient, *, email: str) -> None:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": KNOWN_PASSWORD}
    )
    client.cookies.set(COOKIE_NAME, response.cookies[COOKIE_NAME])


async def _enroll_and_enable_2fa(client: AsyncClient, *, email: str) -> None:
    """Log in as `email`, enroll and confirm 2FA, then log back out."""
    await _login(client, email=email)
    enroll = await client.post("/api/auth/2fa/enroll")
    secret = enroll.json()["secret"]
    await client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    client.cookies.delete(COOKIE_NAME)


async def test_administrator_can_reach_the_admin_stub_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-stub@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-stub@example.com")

    response = await client.get("/api/admin/ping")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_learner_is_forbidden_from_the_admin_stub_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-stub@example.com", role_name="Learner")
    await _login(client, email="learner-stub@example.com")

    response = await client.get("/api/admin/ping")

    assert response.status_code == 403


async def test_content_manager_is_forbidden_from_the_admin_stub_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="content-manager-stub@example.com", role_name="Content Manager"
    )
    await _login(client, email="content-manager-stub@example.com")

    response = await client.get("/api/admin/ping")

    assert response.status_code == 403


async def test_admin_stub_endpoint_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/admin/ping")

    assert response.status_code == 401


async def test_admin_can_disable_a_users_two_factor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-2fa-disable@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-2fa@example.com", role_name="Learner"
    )
    await _enroll_and_enable_2fa(client, email="target-2fa@example.com")
    await _login(client, email="admin-2fa-disable@example.com")

    response = await client.post(
        "/api/admin/users/2fa/disable", json={"email": "target-2fa@example.com"}
    )

    assert response.status_code == 204
    assert await db_session.get(TwoFactorCredential, target.id) is None
    remaining_codes = (
        (await db_session.execute(select(RecoveryCode).where(RecoveryCode.user_id == target.id)))
        .scalars()
        .all()
    )
    assert remaining_codes == []

    audit_entry = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "two_factor_admin_disabled")
        )
    ).scalar_one()
    assert audit_entry.target_user_id == target.id
    assert audit_entry.detail["email"] == "target-2fa@example.com"


async def test_admin_disable_invalidates_the_targets_other_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-2fa-session-disable@example.com", role_name="Administrator"
    )
    await _make_user_with_role(
        db_session, email="target-session-2fa@example.com", role_name="Learner"
    )

    await _login(client, email="target-session-2fa@example.com")
    enroll = await client.post("/api/auth/2fa/enroll")
    secret = enroll.json()["secret"]
    await client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    client.cookies.delete(COOKIE_NAME)

    login = await client.post(
        "/api/auth/login",
        json={"email": "target-session-2fa@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(CHALLENGE_COOKIE_NAME, login.cookies[CHALLENGE_COOKIE_NAME])
    verify = await client.post("/api/auth/2fa/verify", json={"code": pyotp.TOTP(secret).now()})
    target_token = verify.cookies[COOKIE_NAME]
    client.cookies.delete(COOKIE_NAME)

    await _login(client, email="admin-2fa-session-disable@example.com")
    response = await client.post(
        "/api/admin/users/2fa/disable", json={"email": "target-session-2fa@example.com"}
    )
    assert response.status_code == 204

    client.cookies.set(COOKIE_NAME, target_token)
    now_invalid = await client.get("/api/auth/me")
    assert now_invalid.status_code == 401


async def test_admin_disable_for_unknown_email_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-2fa-unknown@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-2fa-unknown@example.com")

    response = await client.post(
        "/api/admin/users/2fa/disable", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 404


async def test_admin_disable_when_not_enabled_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-2fa-not-enabled@example.com", role_name="Administrator"
    )
    await _make_user_with_role(
        db_session, email="never-enrolled@example.com", role_name="Learner"
    )
    await _login(client, email="admin-2fa-not-enabled@example.com")

    response = await client.post(
        "/api/admin/users/2fa/disable", json={"email": "never-enrolled@example.com"}
    )

    assert response.status_code == 409


async def test_non_admin_is_forbidden_from_disabling_another_users_two_factor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="learner-2fa-disable@example.com", role_name="Learner"
    )
    await _make_user_with_role(
        db_session, email="target-forbidden-2fa@example.com", role_name="Learner"
    )
    await _enroll_and_enable_2fa(client, email="target-forbidden-2fa@example.com")
    await _login(client, email="learner-2fa-disable@example.com")

    response = await client.post(
        "/api/admin/users/2fa/disable", json={"email": "target-forbidden-2fa@example.com"}
    )

    assert response.status_code == 403

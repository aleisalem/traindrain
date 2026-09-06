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


async def test_admin_can_list_users(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user_with_role(db_session, email="admin-list@example.com", role_name="Administrator")
    target = await _make_user_with_role(
        db_session, email="listed-learner@example.com", role_name="Learner"
    )
    await _login(client, email="admin-list@example.com")

    response = await client.get("/api/admin/users")

    assert response.status_code == 200
    emails = {row["email"]: row for row in response.json()}
    assert "listed-learner@example.com" in emails
    listed = emails["listed-learner@example.com"]
    assert listed["id"] == str(target.id)
    assert listed["roles"] == ["Learner"]
    assert listed["disabled_at"] is None
    assert listed["erased_at"] is None


async def test_learner_is_forbidden_from_listing_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-list@example.com", role_name="Learner")
    await _login(client, email="learner-list@example.com")

    response = await client.get("/api/admin/users")

    assert response.status_code == 403


async def test_admin_can_disable_a_user(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user_with_role(
        db_session, email="admin-disable@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-disable@example.com", role_name="Learner"
    )
    await _login(client, email="admin-disable@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/disable")

    assert response.status_code == 204
    assert target.disabled_at is not None

    login_attempt = await client.post(
        "/api/auth/login",
        json={"email": "target-disable@example.com", "password": KNOWN_PASSWORD},
    )
    assert login_attempt.status_code == 401

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "user_disabled"))
    ).scalar_one()
    assert audit_entry.target_user_id == target.id
    assert audit_entry.detail["email"] == "target-disable@example.com"


async def test_admin_disable_revokes_the_targets_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-disable-session@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-disable-session@example.com", role_name="Learner"
    )
    login_response = await client.post(
        "/api/auth/login",
        json={"email": "target-disable-session@example.com", "password": KNOWN_PASSWORD},
    )
    target_token = login_response.cookies[COOKIE_NAME]
    client.cookies.delete(COOKIE_NAME)

    await _login(client, email="admin-disable-session@example.com")
    response = await client.post(f"/api/admin/users/{target.id}/disable")
    assert response.status_code == 204

    client.cookies.set(COOKIE_NAME, target_token)
    now_invalid = await client.get("/api/auth/me")
    assert now_invalid.status_code == 401


async def test_disabling_an_already_disabled_user_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-double-disable@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-double-disable@example.com", role_name="Learner"
    )
    await _login(client, email="admin-double-disable@example.com")
    await client.post(f"/api/admin/users/{target.id}/disable")

    response = await client.post(f"/api/admin/users/{target.id}/disable")

    assert response.status_code == 409


async def test_admin_cannot_disable_their_own_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user_with_role(
        db_session, email="admin-self-disable@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-self-disable@example.com")

    response = await client.post(f"/api/admin/users/{admin.id}/disable")

    assert response.status_code == 409
    assert admin.disabled_at is None


async def test_disabling_an_unknown_user_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-disable-unknown@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-disable-unknown@example.com")

    response = await client.post(f"/api/admin/users/{uuid.uuid4()}/disable")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_disabling_a_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="learner-disable@example.com", role_name="Learner"
    )
    target = await _make_user_with_role(
        db_session, email="target-forbidden-disable@example.com", role_name="Learner"
    )
    await _login(client, email="learner-disable@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/disable")

    assert response.status_code == 403


async def test_admin_can_re_enable_a_disabled_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-enable@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-enable@example.com", role_name="Learner"
    )
    await _login(client, email="admin-enable@example.com")
    await client.post(f"/api/admin/users/{target.id}/disable")

    response = await client.post(f"/api/admin/users/{target.id}/enable")

    assert response.status_code == 204
    assert target.disabled_at is None

    login_attempt = await client.post(
        "/api/auth/login",
        json={"email": "target-enable@example.com", "password": KNOWN_PASSWORD},
    )
    assert login_attempt.status_code == 200

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "user_enabled"))
    ).scalar_one()
    assert audit_entry.target_user_id == target.id


async def test_enabling_a_user_that_is_not_disabled_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-enable-not-disabled@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-not-disabled@example.com", role_name="Learner"
    )
    await _login(client, email="admin-enable-not-disabled@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/enable")

    assert response.status_code == 409


async def test_enabling_an_erased_user_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-enable-erased@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-erased-enable@example.com", role_name="Learner"
    )
    await _login(client, email="admin-enable-erased@example.com")
    await client.post(f"/api/admin/users/{target.id}/erase")

    response = await client.post(f"/api/admin/users/{target.id}/enable")

    assert response.status_code == 409


async def test_admin_can_erase_a_user(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user_with_role(
        db_session, email="admin-erase@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-erase@example.com", role_name="Learner"
    )
    target.first_name = "Erasable"
    target.last_name = "Learner"
    await db_session.commit()
    target_id = target.id
    await _login(client, email="admin-erase@example.com")

    response = await client.post(f"/api/admin/users/{target_id}/erase")

    assert response.status_code == 204
    assert target.email == f"erased-user-{target_id}@erased.invalid"
    assert target.first_name is None
    assert target.last_name is None
    assert target.erased_at is not None
    assert target.disabled_at is not None

    # The tombstone row still resolves the audit-log foreign key, and the
    # erased personal data isn't re-logged into the (permanent) audit detail.
    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "user_erased"))
    ).scalar_one()
    assert audit_entry.target_user_id == target_id
    assert "email" not in audit_entry.detail
    assert "target-erase@example.com" not in str(audit_entry.detail)

    login_attempt = await client.post(
        "/api/auth/login",
        json={"email": "target-erase@example.com", "password": KNOWN_PASSWORD},
    )
    assert login_attempt.status_code == 401


async def test_erase_revokes_the_targets_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-erase-session@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-erase-session@example.com", role_name="Learner"
    )
    login_response = await client.post(
        "/api/auth/login",
        json={"email": "target-erase-session@example.com", "password": KNOWN_PASSWORD},
    )
    target_token = login_response.cookies[COOKIE_NAME]
    client.cookies.delete(COOKIE_NAME)

    await _login(client, email="admin-erase-session@example.com")
    response = await client.post(f"/api/admin/users/{target.id}/erase")
    assert response.status_code == 204

    client.cookies.set(COOKIE_NAME, target_token)
    now_invalid = await client.get("/api/auth/me")
    assert now_invalid.status_code == 401


async def test_erasing_an_already_erased_user_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-double-erase@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-double-erase@example.com", role_name="Learner"
    )
    await _login(client, email="admin-double-erase@example.com")
    await client.post(f"/api/admin/users/{target.id}/erase")

    response = await client.post(f"/api/admin/users/{target.id}/erase")

    assert response.status_code == 409


async def test_admin_cannot_erase_their_own_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user_with_role(
        db_session, email="admin-self-erase@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-self-erase@example.com")

    response = await client.post(f"/api/admin/users/{admin.id}/erase")

    assert response.status_code == 409
    assert admin.erased_at is None


async def test_erasing_an_unknown_user_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-erase-unknown@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-erase-unknown@example.com")

    response = await client.post(f"/api/admin/users/{uuid.uuid4()}/erase")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_erasing_a_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-erase@example.com", role_name="Learner")
    target = await _make_user_with_role(
        db_session, email="target-forbidden-erase@example.com", role_name="Learner"
    )
    await _login(client, email="learner-erase@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/erase")

    assert response.status_code == 403


async def _get_role_id(db_session: AsyncSession, role_name: str) -> uuid.UUID:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    return role.id


async def test_admin_can_view_a_roles_members(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-view-role-members@example.com", role_name="Administrator"
    )
    member = await _make_user_with_role(
        db_session, email="member-view-role@example.com", role_name="Learner"
    )
    await _make_user_with_role(
        db_session, email="non-member-view-role@example.com", role_name="Content Manager"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="admin-view-role-members@example.com")

    response = await client.get(f"/api/admin/roles/{learner_id}/members")

    assert response.status_code == 200
    emails = {row["email"] for row in response.json()}
    assert "member-view-role@example.com" in emails
    assert "non-member-view-role@example.com" not in emails
    listed = next(row for row in response.json() if row["email"] == member.email)
    assert listed["id"] == str(member.id)


async def test_viewing_members_of_an_unknown_role_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-view-unknown-role@example.com", role_name="Administrator"
    )
    await _login(client, email="admin-view-unknown-role@example.com")

    response = await client.get(f"/api/admin/roles/{uuid.uuid4()}/members")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_viewing_role_members(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="learner-view-role-members@example.com", role_name="Learner"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="learner-view-role-members@example.com")

    response = await client.get(f"/api/admin/roles/{learner_id}/members")

    assert response.status_code == 403


async def test_admin_can_remove_a_role_from_an_erased_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-remove-erased-role@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-remove-erased-role@example.com", role_name="Learner"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="admin-remove-erased-role@example.com")
    await client.post(f"/api/admin/users/{target.id}/erase")

    response = await client.delete(f"/api/admin/users/{target.id}/roles/{learner_id}")

    assert response.status_code == 204
    await db_session.refresh(target, attribute_names=["roles"])
    assert target.roles == []


async def test_admin_can_assign_a_role_to_a_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-assign-role@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-assign-role@example.com", role_name="Learner"
    )
    content_manager_id = await _get_role_id(db_session, "Content Manager")
    await _login(client, email="admin-assign-role@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/roles/{content_manager_id}")

    assert response.status_code == 204
    await db_session.refresh(target, attribute_names=["roles"])
    assert {role.name for role in target.roles} == {"Learner", "Content Manager"}

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "role_assigned"))
    ).scalar_one()
    assert audit_entry.target_user_id == target.id
    assert audit_entry.detail["role"] == "Content Manager"


async def test_assigning_an_already_held_role_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-assign-dup@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-assign-dup@example.com", role_name="Learner"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="admin-assign-dup@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/roles/{learner_id}")

    assert response.status_code == 409


async def test_assigning_an_unknown_role_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-assign-unknown-role@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-assign-unknown-role@example.com", role_name="Learner"
    )
    await _login(client, email="admin-assign-unknown-role@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/roles/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_assigning_a_role_to_an_unknown_user_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-assign-unknown-user@example.com", role_name="Administrator"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="admin-assign-unknown-user@example.com")

    response = await client.post(f"/api/admin/users/{uuid.uuid4()}/roles/{learner_id}")

    assert response.status_code == 404


async def test_assigning_a_role_to_an_erased_user_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-assign-erased@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-assign-erased@example.com", role_name="Learner"
    )
    content_manager_id = await _get_role_id(db_session, "Content Manager")
    await _login(client, email="admin-assign-erased@example.com")
    await client.post(f"/api/admin/users/{target.id}/erase")

    response = await client.post(f"/api/admin/users/{target.id}/roles/{content_manager_id}")

    assert response.status_code == 409


async def test_non_admin_is_forbidden_from_assigning_a_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="learner-assign-role@example.com", role_name="Learner"
    )
    target = await _make_user_with_role(
        db_session, email="target-forbidden-assign@example.com", role_name="Learner"
    )
    content_manager_id = await _get_role_id(db_session, "Content Manager")
    await _login(client, email="learner-assign-role@example.com")

    response = await client.post(f"/api/admin/users/{target.id}/roles/{content_manager_id}")

    assert response.status_code == 403


async def test_admin_can_remove_a_role_from_a_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-remove-role@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-remove-role@example.com", role_name="Learner"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="admin-remove-role@example.com")

    response = await client.delete(f"/api/admin/users/{target.id}/roles/{learner_id}")

    assert response.status_code == 204
    await db_session.refresh(target, attribute_names=["roles"])
    assert target.roles == []

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "role_removed"))
    ).scalar_one()
    assert audit_entry.target_user_id == target.id
    assert audit_entry.detail["role"] == "Learner"


async def test_removing_a_role_the_user_does_not_have_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-remove-missing@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-remove-missing@example.com", role_name="Learner"
    )
    content_manager_id = await _get_role_id(db_session, "Content Manager")
    await _login(client, email="admin-remove-missing@example.com")

    response = await client.delete(f"/api/admin/users/{target.id}/roles/{content_manager_id}")

    assert response.status_code == 409


async def test_removing_an_unknown_role_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-remove-unknown-role@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-remove-unknown-role@example.com", role_name="Learner"
    )
    await _login(client, email="admin-remove-unknown-role@example.com")

    response = await client.delete(f"/api/admin/users/{target.id}/roles/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_removing_a_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="learner-remove-role@example.com", role_name="Learner"
    )
    target = await _make_user_with_role(
        db_session, email="target-forbidden-remove@example.com", role_name="Learner"
    )
    learner_id = await _get_role_id(db_session, "Learner")
    await _login(client, email="learner-remove-role@example.com")

    response = await client.delete(f"/api/admin/users/{target.id}/roles/{learner_id}")

    assert response.status_code == 403


async def test_role_change_invalidates_the_targets_other_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="admin-role-session@example.com", role_name="Administrator"
    )
    target = await _make_user_with_role(
        db_session, email="target-role-session@example.com", role_name="Learner"
    )
    content_manager_id = await _get_role_id(db_session, "Content Manager")

    login_response = await client.post(
        "/api/auth/login",
        json={"email": "target-role-session@example.com", "password": KNOWN_PASSWORD},
    )
    target_token = login_response.cookies[COOKIE_NAME]
    client.cookies.delete(COOKIE_NAME)

    await _login(client, email="admin-role-session@example.com")
    response = await client.post(f"/api/admin/users/{target.id}/roles/{content_manager_id}")
    assert response.status_code == 204

    client.cookies.set(COOKIE_NAME, target_token)
    now_invalid = await client.get("/api/auth/me")
    assert now_invalid.status_code == 401


async def test_admin_changing_their_own_roles_keeps_their_current_session_alive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _make_user_with_role(
        db_session, email="admin-self-role@example.com", role_name="Administrator"
    )
    content_manager_id = await _get_role_id(db_session, "Content Manager")
    await _login(client, email="admin-self-role@example.com")

    response = await client.post(f"/api/admin/users/{admin.id}/roles/{content_manager_id}")

    assert response.status_code == 204
    still_valid = await client.get("/api/auth/me")
    assert still_valid.status_code == 200

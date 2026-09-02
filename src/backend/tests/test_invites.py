import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Invite, Role, User
from app.security.passwords import hash_password, verify_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


def _latest_invite_token(sent_emails: list[dict[str, Any]]) -> str:
    # The raw token only ever exists in the outgoing email — recover it from
    # there like a real invitee clicking the link would.
    body = sent_emails[-1]["Message"]["Body"]["Text"]["Data"]
    match = re.search(r"token=(\S+)", body)
    assert match is not None
    return match.group(1)


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


async def _login_as_admin(client: AsyncClient, db_session: AsyncSession, *, email: str) -> User:
    admin = await _make_user_with_role(db_session, email=email, role_name="Administrator")
    await _login(client, email=email)
    return admin


async def test_admin_can_issue_an_invite(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-invites@example.com")

    response = await client.post(
        "/api/admin/invites", json={"email": "newbie@example.com", "language": "de"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newbie@example.com"
    assert body["language"] == "de"
    assert body["roles"] == []

    assert len(sent_emails) == 1
    assert sent_emails[0]["Destination"]["ToAddresses"] == ["newbie@example.com"]
    assert "eingeladen" in sent_emails[0]["Message"]["Body"]["Text"]["Data"]

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "invite_sent"))
    ).scalar_one()
    assert audit_entry.detail["email"] == "newbie@example.com"


async def test_non_admin_cannot_issue_an_invite(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user_with_role(db_session, email="learner-invites@example.com", role_name="Learner")
    await _login(client, email="learner-invites@example.com")

    response = await client.post("/api/admin/invites", json={"email": "newbie2@example.com"})

    assert response.status_code == 403


async def test_issuing_an_invite_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/admin/invites", json={"email": "newbie3@example.com"})

    assert response.status_code == 401


async def test_cannot_invite_an_email_that_already_has_an_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-conflict@example.com")
    await _make_user_with_role(db_session, email="existing@example.com", role_name="Learner")

    response = await client.post("/api/admin/invites", json={"email": "existing@example.com"})

    assert response.status_code == 409


async def test_accept_invite_end_to_end(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-e2e@example.com")
    content_manager = (
        await db_session.execute(select(Role).where(Role.name == "Content Manager"))
    ).scalar_one()

    create_response = await client.post(
        "/api/admin/invites",
        json={
            "email": "invitee-e2e@example.com",
            "role_ids": [str(content_manager.id)],
            "language": "de",
        },
    )
    assert create_response.status_code == 201
    token = _latest_invite_token(sent_emails)

    status_response = await client.get(f"/api/invites/{token}")
    assert status_response.status_code == 200
    assert status_response.json() == {"email": "invitee-e2e@example.com", "language": "de"}

    accept_response = await client.post(
        f"/api/invites/{token}/accept", json={"password": KNOWN_PASSWORD}
    )
    assert accept_response.status_code == 204

    user = (
        await db_session.execute(select(User).where(User.email == "invitee-e2e@example.com"))
    ).scalar_one()
    assert verify_password(KNOWN_PASSWORD, user.password_hash)
    assert user.preferred_language == "de"
    assert user.must_change_password is False
    role_names = {role.name for role in user.roles}
    assert role_names == {"Learner", "Content Manager"}

    invite_row = (
        await db_session.execute(
            select(Invite).where(Invite.email == "invitee-e2e@example.com")
        )
    ).scalar_one()
    assert invite_row.accepted_at is not None


async def test_accept_invite_rejects_a_reused_token(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-reuse@example.com")
    await client.post("/api/admin/invites", json={"email": "reuse@example.com"})
    token = _latest_invite_token(sent_emails)

    first = await client.post(f"/api/invites/{token}/accept", json={"password": KNOWN_PASSWORD})
    assert first.status_code == 204

    second = await client.post(f"/api/invites/{token}/accept", json={"password": KNOWN_PASSWORD})
    assert second.status_code == 410


async def test_accept_invite_rejects_a_weak_password(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-weak@example.com")
    await client.post("/api/admin/invites", json={"email": "weak@example.com"})
    token = _latest_invite_token(sent_emails)

    response = await client.post(f"/api/invites/{token}/accept", json={"password": "short"})

    assert response.status_code == 422


async def test_get_invite_status_for_unknown_token_returns_410(client: AsyncClient) -> None:
    response = await client.get("/api/invites/not-a-real-token")

    assert response.status_code == 410


async def test_get_invite_status_for_expired_invite_returns_410(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-expired@example.com")
    await client.post("/api/admin/invites", json={"email": "expired@example.com"})
    token = _latest_invite_token(sent_emails)

    invite_row = (
        await db_session.execute(select(Invite).where(Invite.email == "expired@example.com"))
    ).scalar_one()
    invite_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.get(f"/api/invites/{token}")

    assert response.status_code == 410


async def test_reinviting_the_same_email_invalidates_the_prior_invite(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-reinvite@example.com")

    await client.post("/api/admin/invites", json={"email": "reinvite@example.com"})
    first_token = _latest_invite_token(sent_emails)

    await client.post("/api/admin/invites", json={"email": "reinvite@example.com"})
    second_token = _latest_invite_token(sent_emails)

    assert first_token != second_token

    stale_response = await client.get(f"/api/invites/{first_token}")
    assert stale_response.status_code == 410

    fresh_response = await client.get(f"/api/invites/{second_token}")
    assert fresh_response.status_code == 200


async def test_invite_expiry_setting_defaults_and_is_admin_configurable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-settings@example.com")

    default_response = await client.get("/api/admin/settings/invite-expiry-days")
    assert default_response.status_code == 200
    assert default_response.json() == {"days": 7}

    update_response = await client.put(
        "/api/admin/settings/invite-expiry-days", json={"days": 3}
    )
    assert update_response.status_code == 200
    assert update_response.json() == {"days": 3}

    followup_response = await client.get("/api/admin/settings/invite-expiry-days")
    assert followup_response.json() == {"days": 3}


async def test_invite_expiry_setting_is_admin_only(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user_with_role(
        db_session, email="learner-settings@example.com", role_name="Learner"
    )
    await _login(client, email="learner-settings@example.com")

    response = await client.get("/api/admin/settings/invite-expiry-days")

    assert response.status_code == 403

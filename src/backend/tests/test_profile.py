import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user(db_session: AsyncSession, *, email: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Ada",
        last_name="Lovelace",
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client: AsyncClient, *, email: str) -> None:
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": KNOWN_PASSWORD}
    )
    client.cookies.set(COOKIE_NAME, login.cookies[COOKIE_NAME])


async def test_update_name(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="profile-name@example.com")
    await _login(client, email=user.email)

    response = await client.patch(
        "/api/profile/name", json={"first_name": "Grace", "last_name": "Hopper"}
    )

    assert response.status_code == 200
    assert response.json()["first_name"] == "Grace"
    assert response.json()["last_name"] == "Hopper"

    await db_session.refresh(user)
    assert user.first_name == "Grace"
    assert user.last_name == "Hopper"


async def test_update_name_rejects_blank_values(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="profile-blank-name@example.com")
    await _login(client, email=user.email)

    response = await client.patch(
        "/api/profile/name", json={"first_name": "  ", "last_name": "Hopper"}
    )

    assert response.status_code == 422


async def test_update_name_rejects_an_attempt_to_edit_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="profile-email-immutable@example.com")
    await _login(client, email=user.email)

    response = await client.patch(
        "/api/profile/name",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "new@example.com"},
    )

    assert response.status_code == 422

    await db_session.refresh(user)
    assert user.email == "profile-email-immutable@example.com"


async def test_update_preferences(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="profile-preferences@example.com")
    await _login(client, email=user.email)

    response = await client.patch(
        "/api/profile/preferences",
        json={"preferred_language": "de", "preferred_theme": "dark"},
    )

    assert response.status_code == 200
    assert response.json()["preferred_language"] == "de"
    assert response.json()["preferred_theme"] == "dark"

    await db_session.refresh(user)
    assert user.preferred_language == "de"
    assert user.preferred_theme == "dark"


async def test_preferences_persist_across_a_new_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="profile-new-session@example.com")
    await _login(client, email=user.email)
    await client.patch(
        "/api/profile/preferences",
        json={"preferred_language": "de", "preferred_theme": "dark"},
    )

    # A fresh login (a different session than the one that set the
    # preference) still sees it — it's stored on the user record, not tied
    # to the session that set it.
    client.cookies.delete(COOKIE_NAME)
    await _login(client, email=user.email)
    me = await client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["preferred_language"] == "de"
    assert me.json()["preferred_theme"] == "dark"


async def test_update_preferences_rejects_an_unsupported_theme(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="profile-bad-theme@example.com")
    await _login(client, email=user.email)

    response = await client.patch(
        "/api/profile/preferences",
        json={"preferred_language": "en", "preferred_theme": "neon"},
    )

    assert response.status_code == 422


async def test_new_user_has_no_stored_preferences(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="profile-fresh-user@example.com")
    await _login(client, email=user.email)

    me = await client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["preferred_language"] is None
    assert me.json()["preferred_theme"] is None


async def test_profile_endpoints_require_authentication(client: AsyncClient) -> None:
    name_response = await client.patch(
        "/api/profile/name", json={"first_name": "Grace", "last_name": "Hopper"}
    )
    preferences_response = await client.patch(
        "/api/profile/preferences",
        json={"preferred_language": "en", "preferred_theme": "light"},
    )

    assert name_response.status_code == 401
    assert preferences_response.status_code == 401


async def test_self_service_password_change_invalidates_other_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The password-change endpoint itself is ticket 3's — this just confirms
    # the ticket 12 requirement that it's usable as ordinary self-service
    # (not only under a forced first-login change) and still invalidates the
    # user's other sessions, from the profile page's point of view.
    user = await _make_user(db_session, email="profile-password-change@example.com")
    first_login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": KNOWN_PASSWORD}
    )
    second_login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": KNOWN_PASSWORD}
    )
    first_token = first_login.cookies[COOKIE_NAME]
    second_token = second_login.cookies[COOKIE_NAME]

    client.cookies.set(COOKIE_NAME, first_token)
    changed = await client.post(
        "/api/auth/change-password",
        json={"current_password": KNOWN_PASSWORD, "new_password": "a-fresh-new-passphrase"},
    )
    assert changed.status_code == 200

    client.cookies.set(COOKIE_NAME, first_token)
    still_valid = await client.get("/api/auth/me")
    client.cookies.set(COOKIE_NAME, second_token)
    now_invalid = await client.get("/api/auth/me")

    assert still_valid.status_code == 200
    assert now_invalid.status_code == 401


async def test_update_name_does_not_affect_other_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="profile-self-only@example.com")
    other = await _make_user(db_session, email="profile-bystander@example.com")
    await _login(client, email=user.email)

    await client.patch("/api/profile/name", json={"first_name": "Grace", "last_name": "Hopper"})

    unchanged = (
        await db_session.execute(select(User).where(User.id == other.id))
    ).scalar_one()
    assert unchanged.first_name == "Ada"
    assert unchanged.last_name == "Lovelace"

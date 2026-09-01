import hashlib
import uuid

import httpx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_http_client
from app.main import app
from app.models import Session as SessionModel
from app.models import User
from app.security.passwords import hash_password
from app.security.rate_limit import MAX_ATTEMPTS
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user(
    db_session: AsyncSession, *, email: str, must_change_password: bool = False
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        must_change_password=must_change_password,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_login_succeeds_and_sets_session_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="login-success@example.com")

    response = await client.post(
        "/api/auth/login",
        json={"email": "login-success@example.com", "password": KNOWN_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {"must_change_password": False}
    assert COOKIE_NAME in response.cookies
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=strict" in cookie_header


async def test_login_rejects_wrong_password_with_generic_message(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="login-wrong-password@example.com")

    response = await client.post(
        "/api/auth/login",
        json={"email": "login-wrong-password@example.com", "password": "not-the-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


async def test_login_rejects_unknown_email_with_the_same_generic_message(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"email": "nobody-here@example.com", "password": "whatever-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


async def test_login_email_matching_is_case_insensitive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="Case.Login@Example.com")

    response = await client.post(
        "/api/auth/login",
        json={"email": "case.login@example.com", "password": KNOWN_PASSWORD},
    )

    assert response.status_code == 200


async def test_repeated_failed_logins_are_rate_limited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="brute-forced@example.com")

    for _ in range(MAX_ATTEMPTS):
        response = await client.post(
            "/api/auth/login",
            json={"email": "brute-forced@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked = await client.post(
        "/api/auth/login",
        json={"email": "brute-forced@example.com", "password": KNOWN_PASSWORD},
    )

    assert blocked.status_code == 429


async def test_logout_revokes_the_session_and_clears_the_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="logout-me@example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": "logout-me@example.com", "password": KNOWN_PASSWORD},
    )
    token = login.cookies[COOKIE_NAME]
    client.cookies.set(COOKIE_NAME, token)

    logout = await client.post("/api/auth/logout")

    assert logout.status_code == 204
    assert logout.cookies.get(COOKIE_NAME) is None

    session = (
        await db_session.execute(select(SessionModel).where(SessionModel.user_id == user.id))
    ).scalar_one()
    assert session.revoked_at is not None

    client.cookies.set(COOKIE_NAME, token)
    me_after_logout = await client.get("/api/auth/me")
    assert me_after_logout.status_code == 401


async def test_me_requires_a_valid_session(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_forced_password_change_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="must-change@example.com", must_change_password=True)

    login = await client.post(
        "/api/auth/login",
        json={"email": "must-change@example.com", "password": KNOWN_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json() == {"must_change_password": True}
    token = login.cookies[COOKIE_NAME]
    client.cookies.set(COOKIE_NAME, token)

    # A forced-change user is blocked from every endpoint except logging out
    # and setting a new password — including /me itself.
    me = await client.get("/api/auth/me")
    assert me.status_code == 403
    assert me.json()["detail"]["code"] == "password_change_required"

    new_password = "a-brand-new-passphrase"
    changed = await client.post(
        "/api/auth/change-password",
        json={"current_password": KNOWN_PASSWORD, "new_password": new_password},
    )
    assert changed.status_code == 200
    assert changed.json() == {"must_change_password": False}

    client.cookies.set(COOKIE_NAME, token)
    me_after = await client.get("/api/auth/me")
    assert me_after.json()["must_change_password"] is False

    relogin = await client.post(
        "/api/auth/login",
        json={"email": "must-change@example.com", "password": new_password},
    )
    assert relogin.status_code == 200
    assert relogin.json() == {"must_change_password": False}


async def test_change_password_rejects_wrong_current_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="wrong-current@example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": "wrong-current@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(COOKIE_NAME, login.cookies[COOKIE_NAME])

    response = await client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-current-password", "new_password": "irrelevant-long-one"},
    )

    assert response.status_code == 401


async def test_change_password_enforces_the_minimum_length_policy(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="too-short@example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": "too-short@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(COOKIE_NAME, login.cookies[COOKIE_NAME])

    response = await client.post(
        "/api/auth/change-password",
        json={"current_password": KNOWN_PASSWORD, "new_password": "short1234"},
    )

    assert response.status_code == 422
    assert any("12 characters" in reason for reason in response.json()["detail"]["reasons"])


async def test_change_password_rejects_a_breached_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="breached@example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": "breached@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(COOKIE_NAME, login.cookies[COOKIE_NAME])
    new_password = "definitely-breached-pw"
    sha1_hex = hashlib.sha1(new_password.encode("utf-8")).hexdigest().upper()
    suffix = sha1_hex[5:]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"{suffix}:123")

    async def override_get_http_client():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as mock_client:
            yield mock_client

    app.dependency_overrides[get_http_client] = override_get_http_client
    try:
        response = await client.post(
            "/api/auth/change-password",
            json={"current_password": KNOWN_PASSWORD, "new_password": new_password},
        )
    finally:
        del app.dependency_overrides[get_http_client]

    assert response.status_code == 422
    assert any("breach" in reason for reason in response.json()["detail"]["reasons"])


async def test_change_password_invalidates_other_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="multi-session@example.com")

    first_login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session@example.com", "password": KNOWN_PASSWORD},
    )
    second_login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session@example.com", "password": KNOWN_PASSWORD},
    )
    first_token = first_login.cookies[COOKIE_NAME]
    second_token = second_login.cookies[COOKIE_NAME]

    client.cookies.set(COOKIE_NAME, first_token)
    await client.post(
        "/api/auth/change-password",
        json={"current_password": KNOWN_PASSWORD, "new_password": "a-fresh-new-passphrase"},
    )

    client.cookies.set(COOKIE_NAME, first_token)
    still_valid = await client.get("/api/auth/me")
    client.cookies.set(COOKIE_NAME, second_token)
    now_invalid = await client.get("/api/auth/me")

    assert still_valid.status_code == 200
    assert now_invalid.status_code == 401

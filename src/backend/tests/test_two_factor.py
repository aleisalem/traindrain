import uuid

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecoveryCode, TwoFactorCredential, User
from app.security.passwords import hash_password
from app.security.sessions import CHALLENGE_COOKIE_NAME, COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user(db_session: AsyncSession, *, email: str) -> User:
    user = User(id=uuid.uuid4(), email=email, password_hash=hash_password(KNOWN_PASSWORD))
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client: AsyncClient, *, email: str) -> None:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": KNOWN_PASSWORD}
    )
    assert response.status_code == 200
    client.cookies.set(COOKIE_NAME, response.cookies[COOKIE_NAME])


async def _enroll_and_enable(client: AsyncClient) -> list[str]:
    """Log in, enroll, and confirm 2FA — returns the shown-once recovery codes."""
    enroll = await client.post("/api/auth/2fa/enroll")
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    code = pyotp.TOTP(secret).now()
    enable = await client.post("/api/auth/2fa/enable", json={"code": code})
    assert enable.status_code == 200
    return enable.json()["recovery_codes"]


async def test_enroll_returns_a_setup_key_and_qr_code(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="enroll-me@example.com")
    await _login(client, email="enroll-me@example.com")

    response = await client.post("/api/auth/2fa/enroll")

    assert response.status_code == 200
    body = response.json()
    assert len(body["secret"]) >= 16
    assert body["qr_code_data_uri"].startswith("data:image/png;base64,")


async def test_enroll_twice_while_enabled_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="already-enabled@example.com")
    await _login(client, email="already-enabled@example.com")
    await _enroll_and_enable(client)

    response = await client.post("/api/auth/2fa/enroll")

    assert response.status_code == 409


async def test_enable_generates_ten_single_use_recovery_codes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="enable-me@example.com")
    await _login(client, email="enable-me@example.com")

    codes = await _enroll_and_enable(client)

    assert len(codes) == 10
    assert len(set(codes)) == 10
    stored = (
        await db_session.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id))
    ).scalars().all()
    assert len(stored) == 10
    assert all(row.used_at is None for row in stored)
    # Hashed, never stored in plaintext.
    assert all(row.code_hash not in codes for row in stored)

    credential = await db_session.get(TwoFactorCredential, user.id)
    assert credential.enabled_at is not None


async def test_enable_invalidates_other_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="multi-session-2fa@example.com")

    first_login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session-2fa@example.com", "password": KNOWN_PASSWORD},
    )
    second_login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session-2fa@example.com", "password": KNOWN_PASSWORD},
    )
    first_token = first_login.cookies[COOKIE_NAME]
    second_token = second_login.cookies[COOKIE_NAME]

    client.cookies.set(COOKIE_NAME, first_token)
    await _enroll_and_enable(client)

    client.cookies.set(COOKIE_NAME, first_token)
    still_valid = await client.get("/api/auth/me")
    client.cookies.set(COOKIE_NAME, second_token)
    now_invalid = await client.get("/api/auth/me")

    assert still_valid.status_code == 200
    assert now_invalid.status_code == 401


async def test_enable_rejects_an_invalid_code(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="bad-enable-code@example.com")
    await _login(client, email="bad-enable-code@example.com")
    await client.post("/api/auth/2fa/enroll")

    response = await client.post("/api/auth/2fa/enable", json={"code": "000000"})

    assert response.status_code == 401


async def test_enable_without_enrolling_first_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="no-enroll@example.com")
    await _login(client, email="no-enroll@example.com")

    response = await client.post("/api/auth/2fa/enable", json={"code": "123456"})

    assert response.status_code == 400


async def test_me_reports_two_factor_enabled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="me-2fa@example.com")
    await _login(client, email="me-2fa@example.com")

    before = await client.get("/api/auth/me")
    assert before.json()["two_factor_enabled"] is False

    await _enroll_and_enable(client)

    after = await client.get("/api/auth/me")
    assert after.json()["two_factor_enabled"] is True


async def test_login_with_two_factor_enabled_requires_a_second_step(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="two-step@example.com")
    await _login(client, email="two-step@example.com")
    await _enroll_and_enable(client)
    client.cookies.delete(COOKIE_NAME)

    response = await client.post(
        "/api/auth/login", json={"email": "two-step@example.com", "password": KNOWN_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json() == {"must_change_password": False, "two_factor_required": True}
    assert COOKIE_NAME not in response.cookies
    assert CHALLENGE_COOKIE_NAME in response.cookies

    # No real session exists yet — /me must still be unauthenticated.
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


async def test_login_with_a_valid_totp_code_issues_a_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="totp-login@example.com")
    await _login(client, email="totp-login@example.com")
    enroll = await client.post("/api/auth/2fa/enroll")
    secret = enroll.json()["secret"]
    await client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    client.cookies.delete(COOKIE_NAME)

    login = await client.post(
        "/api/auth/login", json={"email": "totp-login@example.com", "password": KNOWN_PASSWORD}
    )
    client.cookies.set(CHALLENGE_COOKIE_NAME, login.cookies[CHALLENGE_COOKIE_NAME])

    response = await client.post("/api/auth/2fa/verify", json={"code": pyotp.TOTP(secret).now()})

    assert response.status_code == 200
    assert response.json() == {"must_change_password": False, "two_factor_required": False}
    assert COOKIE_NAME in response.cookies
    client.cookies.set(COOKIE_NAME, response.cookies[COOKIE_NAME])

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "totp-login@example.com"


async def test_login_with_a_valid_recovery_code_issues_a_session_and_consumes_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="recovery-login@example.com")
    await _login(client, email="recovery-login@example.com")
    codes = await _enroll_and_enable(client)
    client.cookies.delete(COOKIE_NAME)

    login = await client.post(
        "/api/auth/login",
        json={"email": "recovery-login@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(CHALLENGE_COOKIE_NAME, login.cookies[CHALLENGE_COOKIE_NAME])
    first_use = await client.post("/api/auth/2fa/verify", json={"code": codes[0]})
    assert first_use.status_code == 200
    assert COOKIE_NAME in first_use.cookies

    # The same recovery code can't be used again on a fresh login attempt.
    client.cookies.delete(COOKIE_NAME)
    second_login = await client.post(
        "/api/auth/login",
        json={"email": "recovery-login@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(CHALLENGE_COOKIE_NAME, second_login.cookies[CHALLENGE_COOKIE_NAME])
    second_use = await client.post("/api/auth/2fa/verify", json={"code": codes[0]})

    assert second_use.status_code == 401


async def test_login_second_step_rejects_a_bad_code(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="bad-verify-code@example.com")
    await _login(client, email="bad-verify-code@example.com")
    await _enroll_and_enable(client)
    client.cookies.delete(COOKIE_NAME)

    login = await client.post(
        "/api/auth/login",
        json={"email": "bad-verify-code@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(CHALLENGE_COOKIE_NAME, login.cookies[CHALLENGE_COOKIE_NAME])
    response = await client.post("/api/auth/2fa/verify", json={"code": "000000"})

    assert response.status_code == 401
    # Still no real session.
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


async def test_verify_without_a_pending_challenge_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/auth/2fa/verify", json={"code": "123456"})

    assert response.status_code == 401


async def test_disable_removes_credential_and_recovery_codes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="self-disable@example.com")
    await _login(client, email="self-disable@example.com")
    await _enroll_and_enable(client)

    response = await client.post("/api/auth/2fa/disable", json={"password": KNOWN_PASSWORD})

    assert response.status_code == 204
    assert await db_session.get(TwoFactorCredential, user.id) is None
    remaining = (
        (await db_session.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id)))
        .scalars()
        .all()
    )
    assert remaining == []

    me = await client.get("/api/auth/me")
    assert me.json()["two_factor_enabled"] is False


async def test_disable_rejects_the_wrong_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="wrong-password-disable@example.com")
    await _login(client, email="wrong-password-disable@example.com")
    await _enroll_and_enable(client)

    response = await client.post("/api/auth/2fa/disable", json={"password": "not-the-password"})

    assert response.status_code == 401
    assert await db_session.get(TwoFactorCredential, user.id) is not None


async def test_disable_without_two_factor_enabled_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="not-enabled-disable@example.com")
    await _login(client, email="not-enabled-disable@example.com")

    response = await client.post("/api/auth/2fa/disable", json={"password": KNOWN_PASSWORD})

    assert response.status_code == 409


async def test_disable_invalidates_other_active_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, email="multi-session-disable@example.com")
    first_login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session-disable@example.com", "password": KNOWN_PASSWORD},
    )
    first_token = first_login.cookies[COOKIE_NAME]
    client.cookies.set(COOKIE_NAME, first_token)

    enroll = await client.post("/api/auth/2fa/enroll")
    secret = enroll.json()["secret"]
    await client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})

    # Start a second, independent session through the full 2FA login flow
    # (a plain login no longer issues one directly now that 2FA is enabled).
    client.cookies.delete(COOKIE_NAME)
    login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session-disable@example.com", "password": KNOWN_PASSWORD},
    )
    client.cookies.set(CHALLENGE_COOKIE_NAME, login.cookies[CHALLENGE_COOKIE_NAME])
    verify = await client.post("/api/auth/2fa/verify", json={"code": pyotp.TOTP(secret).now()})
    second_token = verify.cookies[COOKIE_NAME]

    client.cookies.set(COOKIE_NAME, first_token)
    await client.post("/api/auth/2fa/disable", json={"password": KNOWN_PASSWORD})

    client.cookies.set(COOKIE_NAME, first_token)
    still_valid = await client.get("/api/auth/me")
    client.cookies.set(COOKIE_NAME, second_token)
    now_invalid = await client.get("/api/auth/me")

    assert still_valid.status_code == 200
    assert now_invalid.status_code == 401

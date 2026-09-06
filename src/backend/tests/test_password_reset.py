import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PasswordResetToken, User
from app.security.passwords import hash_password, verify_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


def _latest_reset_token(sent_emails: list[dict[str, Any]]) -> str:
    # The raw token only ever exists in the outgoing email — recover it from
    # there like a real user clicking the link would.
    body = sent_emails[-1]["Message"]["Body"]["Text"]["Data"]
    match = re.search(r"token=(\S+)", body)
    assert match is not None
    return match.group(1)


async def _make_user(
    db_session: AsyncSession, *, email: str, preferred_language: str | None = None
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        preferred_language=preferred_language,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_forgot_password_sends_a_reset_email_for_a_known_email(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _make_user(db_session, email="forgot-me@example.com", preferred_language="de")

    response = await client.post(
        "/api/auth/forgot-password", json={"email": "forgot-me@example.com"}
    )

    assert response.status_code == 204
    assert len(sent_emails) == 1
    assert sent_emails[0]["Destination"]["ToAddresses"] == ["forgot-me@example.com"]
    assert "Passwort" in sent_emails[0]["Message"]["Body"]["Text"]["Data"]


async def test_forgot_password_for_an_unknown_email_still_returns_204_and_sends_nothing(
    client: AsyncClient, sent_emails: list[dict[str, Any]]
) -> None:
    response = await client.post(
        "/api/auth/forgot-password", json={"email": "nobody-here@example.com"}
    )

    assert response.status_code == 204
    assert sent_emails == []


async def test_reset_password_end_to_end(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    user = await _make_user(db_session, email="reset-me@example.com")
    await client.post("/api/auth/forgot-password", json={"email": "reset-me@example.com"})
    token = _latest_reset_token(sent_emails)
    new_password = "a-brand-new-passphrase"

    response = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": new_password}
    )

    assert response.status_code == 204
    await db_session.refresh(user)
    assert verify_password(new_password, user.password_hash)

    login = await client.post(
        "/api/auth/login", json={"email": "reset-me@example.com", "password": new_password}
    )
    assert login.status_code == 200


async def test_reset_password_rejects_a_reused_token(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _make_user(db_session, email="reuse-reset@example.com")
    await client.post("/api/auth/forgot-password", json={"email": "reuse-reset@example.com"})
    token = _latest_reset_token(sent_emails)

    first = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "a-perfectly-fine-passphrase-2"}
    )
    assert first.status_code == 204

    second = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "another-fine-passphrase"}
    )
    assert second.status_code == 410


async def test_reset_password_rejects_an_expired_token(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _make_user(db_session, email="expired-reset@example.com")
    await client.post("/api/auth/forgot-password", json={"email": "expired-reset@example.com"})
    token = _latest_reset_token(sent_emails)

    reset_token_row = (
        await db_session.execute(select(PasswordResetToken))
    ).scalars().first()
    reset_token_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "a-fine-passphrase-3"}
    )

    assert response.status_code == 410


async def test_reset_password_rejects_an_unknown_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/reset-password",
        json={"token": "not-a-real-token", "password": "a-fine-passphrase-4"},
    )

    assert response.status_code == 410


async def test_reset_password_enforces_the_password_policy(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _make_user(db_session, email="weak-reset@example.com")
    await client.post("/api/auth/forgot-password", json={"email": "weak-reset@example.com"})
    token = _latest_reset_token(sent_emails)

    response = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "short"}
    )

    assert response.status_code == 422


async def test_reset_password_invalidates_other_active_sessions(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _make_user(db_session, email="multi-session-reset@example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": "multi-session-reset@example.com", "password": KNOWN_PASSWORD},
    )
    existing_token = login.cookies[COOKIE_NAME]

    await client.post(
        "/api/auth/forgot-password", json={"email": "multi-session-reset@example.com"}
    )
    reset_token = _latest_reset_token(sent_emails)
    await client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "password": "a-completely-new-passphrase"},
    )

    client.cookies.set(COOKIE_NAME, existing_token)
    response = await client.get("/api/auth/me")

    assert response.status_code == 401


async def test_requesting_a_new_reset_link_supersedes_the_prior_one(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _make_user(db_session, email="superseded-reset@example.com")

    await client.post("/api/auth/forgot-password", json={"email": "superseded-reset@example.com"})
    first_token = _latest_reset_token(sent_emails)

    await client.post("/api/auth/forgot-password", json={"email": "superseded-reset@example.com"})
    second_token = _latest_reset_token(sent_emails)

    assert first_token != second_token

    stale = await client.post(
        "/api/auth/reset-password",
        json={"token": first_token, "password": "a-fine-passphrase-5"},
    )
    assert stale.status_code == 410

    fresh = await client.post(
        "/api/auth/reset-password",
        json={"token": second_token, "password": "a-fine-passphrase-5"},
    )
    assert fresh.status_code == 204

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

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

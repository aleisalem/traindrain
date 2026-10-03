import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModuleEditSession, Role, User
from app.routes.content import PRESENCE_WINDOW
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(
    db_session: AsyncSession,
    *,
    email: str,
    role_name: str = "Content Manager",
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name=first_name,
        last_name=last_name,
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


async def _make_module(client: AsyncClient) -> str:
    response = await client.post(
        "/api/content/modules", json={"title": "Phishing Awareness", "language": "en"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _ping(client: AsyncClient, module_id: str) -> list[dict[str, str]]:
    response = await client.post(f"/api/content/modules/{module_id}/editing")
    assert response.status_code == 200, response.text
    return response.json()["editors"]


# --- Presence ---


async def test_an_author_alone_in_a_module_sees_nobody_else(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="alone@example.com")
    await _login(client, email="alone@example.com")
    module_id = await _make_module(client)

    assert await _ping(client, module_id) == []


async def test_an_author_sees_who_else_has_the_module_open(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="first@example.com", first_name="Cora", last_name="Manager"
    )
    other = await _make_user_with_role(
        db_session, email="second@example.com", first_name="Ed", last_name="Itor"
    )

    await _login(client, email="first@example.com")
    module_id = await _make_module(client)
    await _ping(client, module_id)

    await _login(client, email="second@example.com")
    editors = await _ping(client, module_id)

    assert [editor["display_name"] for editor in editors] == ["Cora Manager"]
    assert editors[0]["id"] != str(other.id)


async def test_both_authors_see_each_other(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="a@example.com", first_name="Ada")
    await _make_user_with_role(db_session, email="b@example.com", first_name="Grace")

    await _login(client, email="a@example.com")
    module_id = await _make_module(client)
    await _ping(client, module_id)

    await _login(client, email="b@example.com")
    assert [editor["display_name"] for editor in await _ping(client, module_id)] == ["Ada"]

    await _login(client, email="a@example.com")
    assert [editor["display_name"] for editor in await _ping(client, module_id)] == ["Grace"]


async def test_an_author_whose_heartbeat_went_stale_is_no_longer_present(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    stale = await _make_user_with_role(db_session, email="stale@example.com", first_name="Gone")
    await _make_user_with_role(db_session, email="present@example.com", first_name="Here")

    await _login(client, email="present@example.com")
    module_id = await _make_module(client)

    # A closed laptop, a dropped network, a killed tab — whatever the reason,
    # a heartbeat that stopped means the author is no longer in the room.
    db_session.add(
        ModuleEditSession(
            module_id=uuid.UUID(module_id),
            user_id=stale.id,
            last_seen_at=datetime.now(UTC) - PRESENCE_WINDOW - timedelta(seconds=1),
        )
    )
    await db_session.commit()

    assert await _ping(client, module_id) == []


async def test_a_heartbeat_keeps_an_author_present(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    keeper = await _make_user_with_role(db_session, email="keeper@example.com", first_name="Kay")
    await _make_user_with_role(db_session, email="watcher@example.com")

    await _login(client, email="keeper@example.com")
    module_id = await _make_module(client)
    await _ping(client, module_id)

    # Age the row to just inside the window, then heartbeat again.
    session_row = await db_session.get(ModuleEditSession, (uuid.UUID(module_id), keeper.id))
    assert session_row is not None
    session_row.last_seen_at = datetime.now(UTC) - PRESENCE_WINDOW + timedelta(seconds=5)
    await db_session.commit()
    await _ping(client, module_id)

    await _login(client, email="watcher@example.com")
    assert [editor["display_name"] for editor in await _ping(client, module_id)] == ["Kay"]


async def test_a_second_heartbeat_updates_the_row_rather_than_adding_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _make_user_with_role(db_session, email="repeat@example.com")
    await _login(client, email="repeat@example.com")
    module_id = await _make_module(client)

    await _ping(client, module_id)
    await _ping(client, module_id)

    rows = (
        await db_session.execute(
            select(ModuleEditSession).where(
                ModuleEditSession.module_id == uuid.UUID(module_id),
                ModuleEditSession.user_id == author.id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_leaving_the_editor_removes_the_author_immediately(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="leaver@example.com", first_name="Lee")
    await _make_user_with_role(db_session, email="stayer@example.com")

    await _login(client, email="leaver@example.com")
    module_id = await _make_module(client)
    await _ping(client, module_id)

    response = await client.delete(f"/api/content/modules/{module_id}/editing")
    assert response.status_code == 204

    await _login(client, email="stayer@example.com")
    assert await _ping(client, module_id) == []


async def test_leaving_a_module_you_were_never_in_is_not_an_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="never@example.com")
    await _login(client, email="never@example.com")
    module_id = await _make_module(client)

    response = await client.delete(f"/api/content/modules/{module_id}/editing")

    assert response.status_code == 204


async def test_presence_is_scoped_to_one_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="elsewhere@example.com", first_name="Elle")
    await _make_user_with_role(db_session, email="here@example.com")

    await _login(client, email="elsewhere@example.com")
    other_module = await _make_module(client)
    await _ping(client, other_module)

    await _login(client, email="here@example.com")
    this_module = await _make_module(client)

    assert await _ping(client, this_module) == []


async def test_pinging_an_unknown_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="ghost@example.com")
    await _login(client, email="ghost@example.com")

    response = await client.post(f"/api/content/modules/{uuid.uuid4()}/editing")

    assert response.status_code == 404


# --- Authorization ---


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_a_learner_is_forbidden_from_the_presence_routes(
    client: AsyncClient, db_session: AsyncSession, method: str
) -> None:
    await _make_user_with_role(
        db_session, email=f"learner-presence-{method}@example.com", role_name="Learner"
    )
    await _login(client, email=f"learner-presence-{method}@example.com")

    response = await client.request(
        method, f"/api/content/modules/{uuid.uuid4()}/editing"
    )

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_an_anonymous_visitor_is_unauthenticated_on_the_presence_routes(
    client: AsyncClient, method: str
) -> None:
    response = await client.request(
        method, f"/api/content/modules/{uuid.uuid4()}/editing"
    )

    assert response.status_code == 401

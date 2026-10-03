import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Module, ModuleTranslationGroup, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(
    db_session: AsyncSession,
    *,
    email: str,
    role_name: str,
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


async def _login_with_role(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    email: str,
    role_name: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    user = await _make_user_with_role(
        db_session, email=email, role_name=role_name, first_name=first_name, last_name=last_name
    )
    await _login(client, email=email)
    return user


def _module_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Phishing Awareness",
        "description": "How to spot a phish.",
        "language": "en",
        "estimated_duration_minutes": 15,
    }
    payload.update(overrides)
    return payload


# --- Module CRUD ---


async def test_content_manager_can_create_a_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client,
        db_session,
        email="cm-create@example.com",
        role_name="Content Manager",
        first_name="Cora",
        last_name="Manager",
    )

    response = await client.post("/api/content/modules", json=_module_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Phishing Awareness"
    assert body["description"] == "How to spot a phish."
    assert body["language"] == "en"
    assert body["estimated_duration_minutes"] == 15
    assert body["status"] == "draft"
    assert body["created_by"]["display_name"] == "Cora Manager"
    assert body["last_edited_by"]["display_name"] == "Cora Manager"

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "module_created"))
    ).scalar_one()
    assert audit_entry.actor_user_id == author.id
    assert audit_entry.detail["module_id"] == body["id"]
    assert audit_entry.detail["title"] == "Phishing Awareness"


async def test_creating_a_module_auto_creates_a_translation_group_holding_it_as_primary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-group@example.com", role_name="Content Manager"
    )

    response = await client.post("/api/content/modules", json=_module_payload())

    assert response.status_code == 201
    body = response.json()
    group = await db_session.get(ModuleTranslationGroup, uuid.UUID(body["translation_group_id"]))
    assert group is not None
    assert str(group.primary_module_id) == body["id"]


async def test_an_author_without_a_name_is_identified_by_their_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-nameless@example.com", role_name="Content Manager"
    )

    response = await client.post("/api/content/modules", json=_module_payload())

    assert response.status_code == 201
    assert response.json()["created_by"]["display_name"] == "cm-nameless@example.com"


async def test_content_manager_can_list_modules(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-list@example.com", role_name="Content Manager"
    )
    created = await client.post(
        "/api/content/modules", json=_module_payload(title="Data Protection")
    )

    response = await client.get("/api/content/modules")

    assert response.status_code == 200
    titles = {module["title"] for module in response.json()}
    assert "Data Protection" in titles
    assert created.json()["id"] in {module["id"] for module in response.json()}


async def test_content_manager_can_read_one_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-read@example.com", role_name="Content Manager"
    )
    module_id = (await client.post("/api/content/modules", json=_module_payload())).json()["id"]

    response = await client.get(f"/api/content/modules/{module_id}")

    assert response.status_code == 200
    assert response.json()["id"] == module_id


async def test_reading_an_unknown_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-missing@example.com", role_name="Content Manager"
    )

    response = await client.get(f"/api/content/modules/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_content_manager_can_update_module_metadata(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-author@example.com", role_name="Content Manager"
    )
    module_id = (await client.post("/api/content/modules", json=_module_payload())).json()["id"]

    editor = await _login_with_role(
        client,
        db_session,
        email="cm-editor@example.com",
        role_name="Content Manager",
        first_name="Ed",
        last_name="Itor",
    )
    response = await client.patch(
        f"/api/content/modules/{module_id}",
        json={"title": "Phishing Awareness 2026", "estimated_duration_minutes": 20},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Phishing Awareness 2026"
    assert body["estimated_duration_minutes"] == 20
    # Unmentioned fields are left alone — this is a PATCH, not a replace.
    assert body["description"] == "How to spot a phish."
    # created_by records the original author; last_edited_by moves to whoever wrote last.
    assert body["created_by"]["display_name"] == "cm-author@example.com"
    assert body["last_edited_by"]["display_name"] == "Ed Itor"

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "module_updated"))
    ).scalar_one()
    assert audit_entry.actor_user_id == editor.id
    assert audit_entry.detail["module_id"] == module_id


async def test_updating_an_unknown_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-patch-missing@example.com", role_name="Content Manager"
    )

    response = await client.patch(f"/api/content/modules/{uuid.uuid4()}", json={"title": "Nope"})

    assert response.status_code == 404


@pytest.mark.parametrize("field", ["created_by", "last_edited_by", "status", "language"])
async def test_server_owned_fields_are_never_accepted_from_the_client(
    client: AsyncClient, db_session: AsyncSession, field: str
) -> None:
    await _login_with_role(
        client, db_session, email=f"cm-smuggle-{field}@example.com", role_name="Content Manager"
    )
    module_id = (await client.post("/api/content/modules", json=_module_payload())).json()["id"]

    response = await client.patch(
        f"/api/content/modules/{module_id}", json={"title": "Retitled", field: "de"}
    )

    assert response.status_code == 422


async def test_creating_a_module_in_an_unsupported_language_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-language@example.com", role_name="Content Manager"
    )

    response = await client.post("/api/content/modules", json=_module_payload(language="fr"))

    assert response.status_code == 422


async def test_creating_a_module_with_a_blank_title_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-blank@example.com", role_name="Content Manager"
    )

    response = await client.post("/api/content/modules", json=_module_payload(title="   "))

    assert response.status_code == 422


async def test_modules_are_created_in_german_too(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="cm-german@example.com", role_name="Content Manager"
    )

    response = await client.post(
        "/api/content/modules", json=_module_payload(language="de", title="Phishing-Bewusstsein")
    )

    assert response.status_code == 201
    assert response.json()["language"] == "de"


async def test_two_modules_cannot_share_a_language_within_one_translation_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _make_user_with_role(
        db_session, email="cm-unique@example.com", role_name="Content Manager"
    )
    group = ModuleTranslationGroup()
    db_session.add(group)
    await db_session.flush()
    for _ in range(2):
        db_session.add(
            Module(
                translation_group_id=group.id,
                language="en",
                title="Duplicate language",
                created_by=author.id,
                last_edited_by=author.id,
            )
        )

    with pytest.raises(Exception):  # noqa: B017 - asyncpg raises its own IntegrityError subclass
        await db_session.flush()


# --- Authorization ---


CONTENT_ROUTES = [
    ("GET", "/api/content/modules"),
    ("POST", "/api/content/modules"),
    ("GET", f"/api/content/modules/{uuid.uuid4()}"),
    ("PATCH", f"/api/content/modules/{uuid.uuid4()}"),
]


@pytest.mark.parametrize(("method", "path"), CONTENT_ROUTES)
async def test_a_learner_is_forbidden_from_every_content_route(
    client: AsyncClient, db_session: AsyncSession, method: str, path: str
) -> None:
    await _login_with_role(
        client, db_session, email=f"learner-{method}-{hash(path)}@example.com", role_name="Learner"
    )

    response = await client.request(method, path, json=_module_payload())

    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), CONTENT_ROUTES)
async def test_an_anonymous_visitor_is_unauthenticated_on_every_content_route(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path, json=_module_payload())

    assert response.status_code == 401


async def test_an_administrator_can_use_the_content_routes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="admin-content@example.com", role_name="Administrator"
    )

    created = await client.post("/api/content/modules", json=_module_payload())
    listed = await client.get("/api/content/modules")

    assert created.status_code == 201
    assert listed.status_code == 200


@pytest.mark.parametrize("path", ["/api/admin/ping", "/api/admin/users", "/api/admin/groups"])
async def test_a_content_manager_cannot_reach_the_admin_routes(
    client: AsyncClient, db_session: AsyncSession, path: str
) -> None:
    await _login_with_role(
        client,
        db_session,
        email=f"cm-admin-{hash(path)}@example.com",
        role_name="Content Manager",
    )

    response = await client.get(path)

    assert response.status_code == 403

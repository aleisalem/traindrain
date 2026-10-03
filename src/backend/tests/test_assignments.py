"""Assignment: who has to read a module, and by when.

Three properties this file holds down.

The first is the data-minimization boundary: a Content Manager may assign a
module to a group, never to a named person, and the read side of the same
endpoint never hands them a colleague's identity either.

The second is that membership is resolved live, not expanded at assign time —
a learner who joins a targeted group afterwards sees the module without
anyone touching the assignment, and one who leaves keeps what they already
completed.

The third is that assignment is what makes an otherwise-hidden module
reachable at all: `may_read_module`'s new branch, exercised end to end through
the learner routes and through asset delivery.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import AuditLog, Group, ModuleProgress, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME
from tests.test_upload_sniffing import PNG

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(
    db_session: AsyncSession,
    *,
    email: str,
    role_name: str,
    preferred_language: str | None = None,
) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Lena",
        last_name="Learner",
        roles=[role],
        preferred_language=preferred_language,
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
    client: AsyncClient, db_session: AsyncSession, *, email: str, role_name: str
) -> User:
    user = await _make_user_with_role(db_session, email=email, role_name=role_name)
    await _login(client, email=email)
    return user


async def _switch_to(client: AsyncClient, db_session: AsyncSession, *, email: str) -> User:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db_session, email=email, role_name="Learner")


async def _make_group(db_session: AsyncSession, *, name: str) -> Group:
    group = Group(name=name)
    db_session.add(group)
    await db_session.commit()
    return group


async def _add_to_group(db_session: AsyncSession, user: User, group: Group) -> None:
    # An async session never lazy-loads a relationship on plain attribute
    # access — that needs an explicit, awaited (re)load.
    await db_session.refresh(user, attribute_names=["groups"])
    user.groups.append(group)
    await db_session.commit()


async def _remove_from_group(db_session: AsyncSession, user: User, group: Group) -> None:
    await db_session.refresh(user, attribute_names=["groups"])
    user.groups.remove(group)
    await db_session.commit()


def _doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def _create_module(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    author_email: str,
    title: str = "Fire Safety",
    publish: bool = True,
    catalog_visible: bool = False,
) -> dict[str, Any]:
    await _login_with_role(client, db_session, email=author_email, role_name="Content Manager")
    created = await client.post(
        "/api/content/modules", json={"title": title, "language": "en"}
    )
    assert created.status_code == 201
    module = created.json()

    page = await client.post(
        f"/api/content/modules/{module['id']}/pages",
        json={
            "draft_revision": 1,
            "title": "Intro",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("The text."),
        },
    )
    assert page.status_code == 201

    if catalog_visible:
        await client.patch(f"/api/content/modules/{module['id']}", json={"catalog_visible": True})

    if publish:
        published = await client.post(
            f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
        )
        assert published.status_code == 200, published.text
        module = published.json()

    return module


def _emails_to(sent_emails: list[dict[str, Any]]) -> list[str]:
    return [
        email["Destination"]["ToAddresses"][0]
        for email in sent_emails
        if "assigned" in email["Message"]["Subject"]["Data"].lower()
        or "zugewiesen" in email["Message"]["Subject"]["Data"].lower()
    ]


# --- The Content Manager / Administrator boundary --------------------------


async def test_a_content_manager_can_assign_a_module_to_a_group(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    module = await _create_module(client, db_session, author_email="cm-assign-author@example.com")
    group = await _make_group(db_session, name="Warehouse Staff")
    member = await _make_user_with_role(
        db_session, email="warehouse-member@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, member, group)

    await _login_with_role(
        client, db_session, email="cm-assign@example.com", role_name="Content Manager"
    )
    response = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={
            "target_type": "group",
            "target_id": str(group.id),
            "requirement": "mandatory",
            "due_date": "2026-12-01",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target"]["type"] == "group"
    assert body["target"]["name"] == "Warehouse Staff"
    assert body["due_date"] == "2026-12-01"
    assert body["requirement"] == "mandatory"

    recipients = _emails_to(sent_emails)
    assert "warehouse-member@example.com" in recipients


async def test_a_learner_who_joins_afterwards_is_not_emailed_retroactively(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    module = await _create_module(client, db_session, author_email="noretro-author@example.com")
    group = await _make_group(db_session, name="No Retroactive Email")
    latecomer = await _make_user_with_role(
        db_session, email="noretro-latecomer@example.com", role_name="Learner"
    )

    await _login_with_role(
        client, db_session, email="noretro-cm@example.com", role_name="Content Manager"
    )
    created = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert created.status_code == 201
    # Nobody was a member at assignment time, so no email went out yet.
    assert _emails_to(sent_emails) == []

    await _add_to_group(db_session, latecomer, group)

    # Joining later grants access (covered elsewhere) but sends no email —
    # membership is resolved live, and only assignment *creation* notifies.
    assert "noretro-latecomer@example.com" not in _emails_to(sent_emails)


async def test_a_content_manager_cannot_assign_a_module_to_an_individual(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="cm-indiv-author@example.com")
    target = await _make_user_with_role(
        db_session, email="cm-indiv-target@example.com", role_name="Learner"
    )
    await _login_with_role(
        client, db_session, email="cm-indiv@example.com", role_name="Content Manager"
    )

    response = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "user", "target_id": str(target.id), "requirement": "mandatory"},
    )

    assert response.status_code == 403


async def test_an_administrator_can_assign_a_module_to_an_individual(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    module = await _create_module(client, db_session, author_email="admin-indiv-author@example.com")
    target = await _make_user_with_role(
        db_session,
        email="admin-indiv-target@example.com",
        role_name="Learner",
        preferred_language="de",
    )
    await _login_with_role(
        client, db_session, email="admin-indiv@example.com", role_name="Administrator"
    )

    response = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "user", "target_id": str(target.id), "requirement": "recommended"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target"]["type"] == "user"
    # An Administrator sees who it is.
    assert body["target"]["name"] is not None

    assert "admin-indiv-target@example.com" in _emails_to(sent_emails)
    # Sent in the target's own preferred language.
    assert (
        sent_emails[-1]["Message"]["Subject"]["Data"]
        == "Ihnen wurde ein neues Training auf TrainDrain zugewiesen"
    )


async def test_assigning_the_same_target_twice_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="dup-assign-author@example.com")
    group = await _make_group(db_session, name="Dup Target Group")
    await _login_with_role(
        client, db_session, email="dup-assign@example.com", role_name="Content Manager"
    )
    first = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "recommended"},
    )

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "already_assigned"


async def test_a_content_manager_never_sees_an_individual_targets_identity(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="hide-author@example.com")
    target = await _make_user_with_role(
        db_session, email="hide-target@example.com", role_name="Learner"
    )
    await _login_with_role(
        client, db_session, email="hide-admin@example.com", role_name="Administrator"
    )
    created = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "user", "target_id": str(target.id), "requirement": "mandatory"},
    )
    assert created.status_code == 201

    await _login_with_role(
        client, db_session, email="hide-cm@example.com", role_name="Content Manager"
    )
    listed = await client.get(f"/api/content/modules/{module['id']}/assignments")

    assert listed.status_code == 200
    row = next(row for row in listed.json() if row["target"]["type"] == "user")
    assert row["target"]["name"] is None
    # The raw id is not itself the colleague's name or email.
    assert row["target"]["id"] == str(target.id)


async def test_a_content_manager_cannot_remove_an_individual_assignment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The same boundary that gates creating an individual assignment gates
    removing one — a Content Manager should not be able to act on a row
    naming a colleague they cannot even identify."""
    module = await _create_module(client, db_session, author_email="delidor-author@example.com")
    target = await _make_user_with_role(
        db_session, email="delidor-target@example.com", role_name="Learner"
    )
    await _login_with_role(
        client, db_session, email="delidor-admin@example.com", role_name="Administrator"
    )
    created = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "user", "target_id": str(target.id), "requirement": "mandatory"},
    )
    assignment_id = created.json()["id"]

    await _login_with_role(
        client, db_session, email="delidor-cm@example.com", role_name="Content Manager"
    )
    response = await client.delete(f"/api/content/assignments/{assignment_id}")

    assert response.status_code == 403


async def test_content_groups_endpoint_shows_names_and_counts_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group = await _make_group(db_session, name="Counted Group")
    member = await _make_user_with_role(
        db_session, email="counted-member@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, member, group)
    await _login_with_role(
        client, db_session, email="groups-cm@example.com", role_name="Content Manager"
    )

    response = await client.get("/api/content/groups")

    assert response.status_code == 200
    row = next(row for row in response.json() if row["id"] == str(group.id))
    assert row["name"] == "Counted Group"
    assert row["member_count"] == 1
    assert "members" not in row
    assert "member_ids" not in row


# --- Dynamic group targeting -------------------------------------------------


async def test_a_user_who_joins_a_targeted_group_later_sees_the_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="joiner-author@example.com")
    group = await _make_group(db_session, name="Joiners")
    await _login_with_role(
        client, db_session, email="joiner-cm@example.com", role_name="Content Manager"
    )
    assigned = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert assigned.status_code == 201

    # Not a member yet: the module is unreachable, exactly as an unassigned
    # non-catalog module would be.
    learner = await _switch_to(client, db_session, email="joiner-learner@example.com")
    blocked = await client.get(f"/api/me/modules/{module['translation_group_id']}")
    assert blocked.status_code == 404

    # They join the group — nothing about the assignment itself changes.
    await _add_to_group(db_session, learner, group)

    opened = await client.get(f"/api/me/modules/{module['translation_group_id']}")
    assert opened.status_code == 200
    assert opened.json()["title"] == "Fire Safety"


async def test_a_user_removed_from_a_targeted_group_loses_the_assignment_but_keeps_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="leaver-author@example.com")
    group = await _make_group(db_session, name="Leavers")
    learner = await _make_user_with_role(
        db_session, email="leaver-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)

    await _login_with_role(
        client, db_session, email="leaver-cm@example.com", role_name="Content Manager"
    )
    await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )

    await _login(client, email="leaver-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await client.get(f"/api/me/modules/{group_id}")).json()["pages"]
    viewed = await client.post(f"/api/me/modules/{group_id}/pages/{pages[0]['id']}/view")
    assert viewed.status_code == 200

    await _remove_from_group(db_session, learner, group)

    # The assignment no longer reaches them...
    blocked = await client.get(f"/api/me/modules/{group_id}")
    assert blocked.status_code == 404

    # ...but the progress they already made is retained, not deleted.
    progress = (
        await db_session.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == learner.id,
                ModuleProgress.translation_group_id == uuid.UUID(group_id),
            )
        )
    ).scalar_one()
    assert progress.pages_viewed == [pages[0]["id"]]


async def test_removing_an_assignment_does_not_delete_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="unassign-author@example.com")
    group = await _make_group(db_session, name="Unassigned Later")
    learner = await _make_user_with_role(
        db_session, email="unassign-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)

    await _login_with_role(
        client, db_session, email="unassign-cm@example.com", role_name="Content Manager"
    )
    created = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assignment_id = created.json()["id"]

    await _login(client, email="unassign-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await client.get(f"/api/me/modules/{group_id}")).json()["pages"]
    for page in pages:
        await client.post(f"/api/me/modules/{group_id}/pages/{page['id']}/view")
    completed = await client.post(f"/api/me/modules/{group_id}/complete")
    assert completed.status_code == 200

    await _login(client, email="unassign-cm@example.com")
    deleted = await client.delete(f"/api/content/assignments/{assignment_id}")
    assert deleted.status_code == 204

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == learner.id,
                ModuleProgress.translation_group_id == uuid.UUID(group_id),
            )
        )
    ).scalar_one()
    assert progress.completed_at is not None


# --- Assets are the same door as the pages ----------------------------------


async def test_an_assigned_learner_can_fetch_an_asset_of_a_non_catalog_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="asset-assign-author@example.com", role_name="Content Manager"
    )
    created = await client.post(
        "/api/content/modules", json={"title": "With an asset", "language": "en"}
    )
    module = created.json()
    await client.post(
        f"/api/content/modules/{module['id']}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    await client.post(
        f"/api/content/modules/{module['id']}/pages",
        json={
            "draft_revision": 1,
            "title": "Intro",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Text."),
        },
    )
    published = await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
    )
    assert published.status_code == 200
    module = published.json()
    assets = (await client.get(f"/api/content/modules/{module['id']}/assets")).json()["assets"]

    group = await _make_group(db_session, name="Asset Assignees")
    await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )

    learner = await _switch_to(client, db_session, email="asset-assign-learner@example.com")

    # Not assigned yet: the asset is unreachable, exactly like the module.
    still_blocked = await client.get(assets[0]["url"], follow_redirects=False)
    assert still_blocked.status_code == 404

    await _add_to_group(db_session, learner, group)
    response = await client.get(assets[0]["url"], follow_redirects=False)

    assert response.status_code == 307


# --- The learner's assigned list --------------------------------------------


async def test_my_modules_lists_an_assigned_but_unstarted_module_with_due_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="unstarted-author@example.com")
    group = await _make_group(db_session, name="Unstarted Assignees")
    learner = await _make_user_with_role(
        db_session, email="unstarted-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)

    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    await _login_with_role(
        client, db_session, email="unstarted-cm@example.com", role_name="Content Manager"
    )
    await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={
            "target_type": "group",
            "target_id": str(group.id),
            "requirement": "mandatory",
            "due_date": yesterday,
        },
    )

    await _login(client, email="unstarted-learner@example.com")
    response = await client.get("/api/me/modules")

    assert response.status_code == 200
    row = next(
        row
        for row in response.json()
        if row["translation_group_id"] == module["translation_group_id"]
    )
    assert row["started_at"] is None
    assert row["completed_at"] is None
    assert row["due_date"] == yesterday
    assert row["requirement"] == "mandatory"
    assert row["overdue"] is True
    assert row["available"] is True


async def test_a_completed_assignment_is_never_overdue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="notoverdue-author@example.com")
    group = await _make_group(db_session, name="Not Overdue")
    learner = await _make_user_with_role(
        db_session, email="notoverdue-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)

    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    await _login_with_role(
        client, db_session, email="notoverdue-cm@example.com", role_name="Content Manager"
    )
    await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={
            "target_type": "group",
            "target_id": str(group.id),
            "requirement": "mandatory",
            "due_date": yesterday,
        },
    )

    await _login(client, email="notoverdue-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await client.get(f"/api/me/modules/{group_id}")).json()["pages"]
    for page in pages:
        await client.post(f"/api/me/modules/{group_id}/pages/{page['id']}/view")
    await client.post(f"/api/me/modules/{group_id}/complete")

    row = next(
        row
        for row in (await client.get("/api/me/modules")).json()
        if row["translation_group_id"] == group_id
    )
    assert row["completed_at"] is not None
    assert row["overdue"] is False


async def test_a_direct_and_a_group_assignment_are_deduplicated_by_nearest_due_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="nearest-author@example.com")
    group = await _make_group(db_session, name="Nearest Due Date")
    learner = await _make_user_with_role(
        db_session, email="nearest-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)

    await _login_with_role(
        client, db_session, email="nearest-admin@example.com", role_name="Administrator"
    )
    await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={
            "target_type": "group",
            "target_id": str(group.id),
            "requirement": "recommended",
            "due_date": "2027-06-01",
        },
    )
    await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={
            "target_type": "user",
            "target_id": str(learner.id),
            "requirement": "mandatory",
            "due_date": "2027-01-01",
        },
    )

    await _login(client, email="nearest-learner@example.com")
    response = await client.get("/api/me/modules")

    rows = [
        row
        for row in response.json()
        if row["translation_group_id"] == module["translation_group_id"]
    ]
    # One row, not two — deduplicated by translation group.
    assert len(rows) == 1
    assert rows[0]["due_date"] == "2027-01-01"
    assert rows[0]["requirement"] == "mandatory"


async def test_my_modules_is_empty_for_a_learner_with_no_progress_and_no_assignment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _switch_to(client, db_session, email="nothing-learner@example.com")
    assert (await client.get("/api/me/modules")).json() == []


# --- Audit log ---------------------------------------------------------------


async def test_assignment_creation_and_removal_are_audit_logged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="audit-author@example.com")
    group = await _make_group(db_session, name="Audited Group")
    await _login_with_role(
        client, db_session, email="audit-cm@example.com", role_name="Content Manager"
    )
    created = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assignment_id = created.json()["id"]

    await client.delete(f"/api/content/assignments/{assignment_id}")

    actions = (
        await db_session.execute(
            select(AuditLog.action).where(
                AuditLog.action.in_(["assignment_created", "assignment_removed"])
            )
        )
    ).scalars()
    assert set(actions) == {"assignment_created", "assignment_removed"}

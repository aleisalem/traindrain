"""Module delete: the tombstone, the purge, and what survives it.

Modelled directly on Release 0's user-erase tombstone. The property this file
holds down is the same split that pattern has: everything that is genuinely
content — pages, version snapshots, stored files — is gone without a trace,
while everything that is evidence a person did something — a `ModuleProgress`
row, an audit entry, an Administrator's report — survives and keeps resolving
against the row that is left behind.

The second property is that `deleted` is terminal, checked from the denied
direction: every other mutating authoring route refuses a deleted module.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import (
    Assignment,
    AuditLog,
    Group,
    Module,
    ModuleAsset,
    ModulePage,
    ModuleProgress,
    ModuleVersion,
    Role,
    User,
)
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME
from tests.test_upload_sniffing import PNG

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(
    db_session: AsyncSession, *, email: str, role_name: str
) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Cora",
        last_name="Manager",
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
    client: AsyncClient, db_session: AsyncSession, *, email: str, role_name: str
) -> User:
    user = await _make_user_with_role(db_session, email=email, role_name=role_name)
    await _login(client, email=email)
    return user


async def _sign_in_as(client: AsyncClient, *, email: str) -> None:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=email)


def _doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def _make_module(
    client: AsyncClient, *, title: str = "Phishing Awareness", language: str = "en"
) -> str:
    response = await client.post(
        "/api/content/modules",
        json={"title": title, "description": "How to spot a phish.", "language": language},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _add_page(
    client: AsyncClient, module_id: str, *, title: str = "Intro", revision: int = 1
) -> dict[str, Any]:
    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": revision,
            "title": title,
            "schema_version": SCHEMA_VERSION,
            "body": _doc(title),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _publish(client: AsyncClient, module_id: str, *, kind: str = "minor") -> dict[str, Any]:
    response = await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": kind}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _published_module_with_page(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    email: str,
    title: str = "Phishing Awareness",
    catalog_visible: bool = True,
) -> dict[str, Any]:
    await _login_with_role(client, db_session, email=email, role_name="Content Manager")
    module_id = await _make_module(client, title=title)
    await _add_page(client, module_id)
    if catalog_visible:
        patched = await client.patch(
            f"/api/content/modules/{module_id}", json={"catalog_visible": True}
        )
        assert patched.status_code == 200
    return await _publish(client, module_id)


async def _become_learner(client: AsyncClient, db_session: AsyncSession, *, email: str) -> User:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db_session, email=email, role_name="Learner")


async def _open(client: AsyncClient, group_id: str) -> Any:
    return await client.get(f"/api/me/modules/{group_id}")


async def _complete(client: AsyncClient, group_id: str) -> dict[str, Any]:
    opened = await _open(client, group_id)
    assert opened.status_code == 200, opened.text
    for page in opened.json()["pages"]:
        viewed = await client.post(f"/api/me/modules/{group_id}/pages/{page['id']}/view")
        assert viewed.status_code == 200, viewed.text
    response = await client.post(f"/api/me/modules/{group_id}/complete")
    assert response.status_code == 200, response.text
    return response.json()


async def _delete(client: AsyncClient, module_id: str) -> Any:
    return await client.delete(f"/api/content/modules/{module_id}")


# --- The purge --------------------------------------------------------------


async def test_delete_purges_pages_versions_and_asset_objects(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    await _login_with_role(
        client, db_session, email="delete-purge@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id)
    uploaded = await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    assert uploaded.status_code == 201
    key = f"modules/{module_id}/assets/{uploaded.json()['assets'][0]['id']}"
    assert key in stored_objects
    await _publish(client, module_id)

    response = await _delete(client, module_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "deleted"
    # The tombstone keeps saying what it is.
    assert body["title"] == "Phishing Awareness"
    assert body["language"] == "en"
    assert body["current_version_number"] is None
    # No version row survives to resolve `current_version_number` against, but
    # the tombstone still says what version it was last on.
    assert body["deleted_version_number"] == 1

    module_uuid = uuid.UUID(module_id)
    pages = (
        await db_session.execute(select(ModulePage).where(ModulePage.module_id == module_uuid))
    ).scalars().all()
    versions = (
        await db_session.execute(
            select(ModuleVersion).where(ModuleVersion.module_id == module_uuid)
        )
    ).scalars().all()
    assets = (
        await db_session.execute(select(ModuleAsset).where(ModuleAsset.module_id == module_uuid))
    ).scalars().all()
    assert pages == []
    assert versions == []
    assert assets == []
    assert key not in stored_objects

    module = await db_session.get(Module, module_uuid)
    assert module is not None
    assert module.status == "deleted"
    assert module.deleted_at is not None
    assert module.current_version_id is None
    assert module.catalog_visible is False
    assert module.deleted_version_number == 1
    # The row survives — that is the whole point of a tombstone.
    assert module.title == "Phishing Awareness"
    assert module.language == "en"


async def test_a_module_deleted_while_still_an_unpublished_draft_has_no_deleted_version(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A module that was never published has no version to remember — the
    tombstone says so honestly rather than claiming a version 0."""
    await _login_with_role(
        client, db_session, email="delete-unpublished@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)

    response = await _delete(client, module_id)
    assert response.status_code == 200, response.text
    assert response.json()["deleted_version_number"] is None


async def test_deleting_twice_is_a_conflict(client: AsyncClient, db_session: AsyncSession) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-twice@example.com"
    )
    first = await _delete(client, module["id"])
    assert first.status_code == 200

    second = await _delete(client, module["id"])
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "already_deleted"


async def test_deleting_a_module_with_no_pages_or_publish_still_works(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A delete makes no assumption a publish would — an unpublished, empty
    draft is exactly as deletable as a well-developed one."""
    await _login_with_role(
        client, db_session, email="delete-empty@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)

    response = await _delete(client, module_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deleted"


async def test_the_module_deleted_audit_entry_carries_the_affected_completion_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-audit-author@example.com"
    )
    group_id = module["translation_group_id"]

    learner = await _become_learner(
        client, db_session, email="delete-audit-learner@example.com"
    )
    await _complete(client, group_id)

    await _sign_in_as(client, email="delete-audit-author@example.com")
    response = await _delete(client, module["id"])
    assert response.status_code == 200

    entry = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "module_deleted")
        )
    ).scalar_one()
    assert entry.detail["module_id"] == module["id"]
    assert entry.detail["affected_completions"] == 1
    del learner  # only needed to have completed the module


# --- The tombstone: what a delete's confirmation is told beforehand --------


async def test_deletion_impact_counts_completions_before_the_delete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-impact-author@example.com"
    )
    group_id = module["translation_group_id"]

    before = await client.get(f"/api/content/modules/{module['id']}/deletion-impact")
    assert before.status_code == 200
    assert before.json()["completion_count"] == 0

    await _become_learner(client, db_session, email="delete-impact-learner@example.com")
    await _complete(client, group_id)

    await _sign_in_as(client, email="delete-impact-author@example.com")
    after = await client.get(f"/api/content/modules/{module['id']}/deletion-impact")
    assert after.status_code == 200
    assert after.json()["completion_count"] == 1


# --- Terminal: every other mutating route refuses a deleted module --------


async def test_a_deleted_module_can_never_be_edited_published_duplicated_or_assigned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="delete-terminal@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id)
    published = await _publish(client, module_id)

    deleted = await _delete(client, module_id)
    assert deleted.status_code == 200

    patched = await client.patch(
        f"/api/content/modules/{module_id}", json={"title": "New title"}
    )
    assert patched.status_code == 409
    assert patched.json()["detail"]["code"] == "module_deleted"

    created_page = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": published["current_version_number"] or 1,
            "title": "Resurrected",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Resurrected"),
        },
    )
    assert created_page.status_code == 409
    assert created_page.json()["detail"]["code"] == "module_deleted"

    publish_again = await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": "minor"}
    )
    assert publish_again.status_code == 409
    assert publish_again.json()["detail"]["code"] == "module_deleted"

    duplicate = await client.post(f"/api/content/modules/{module_id}/duplicate", json={})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "module_deleted"

    group = Group(name="Delete-terminal group")
    db_session.add(group)
    await db_session.commit()
    assigned = await client.post(
        f"/api/content/modules/{module_id}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert assigned.status_code == 409
    assert assigned.json()["detail"]["code"] == "module_deleted"

    uploaded = await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    assert uploaded.status_code == 409
    assert uploaded.json()["detail"]["code"] == "module_deleted"


async def test_a_deleted_module_cannot_be_linked_as_a_translation_variant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Guards against resurrecting a tombstone's content through a side door:
    `link_variant`'s own deleted-source check is exercised end to end."""
    module = await _published_module_with_page(
        client, db_session, email="delete-link-author@example.com"
    )
    await _delete(client, module["id"])

    other = await client.post(
        "/api/content/modules", json={"title": "German Sibling", "language": "de"}
    )
    assert other.status_code == 201
    other_group_id = other.json()["translation_group_id"]

    linked = await client.post(
        f"/api/content/translation-groups/{other_group_id}/variants",
        json={"module_id": module["id"]},
    )
    assert linked.status_code == 409
    assert linked.json()["detail"]["code"] == "module_deleted"


# --- Survival: progress, audit history, and reporting ----------------------


async def test_assignments_are_removed_but_progress_and_audit_history_survive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-survive-author@example.com"
    )
    group_id = module["translation_group_id"]

    group = Group(name="Delete-survive group")
    db_session.add(group)
    await db_session.commit()
    assigned = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert assigned.status_code == 201

    learner = await _become_learner(
        client, db_session, email="delete-survive-learner@example.com"
    )
    await db_session.refresh(learner, attribute_names=["groups"])
    learner.groups.append(group)
    await db_session.commit()
    completion = await _complete(client, group_id)
    assert completion["completed_version_number"] == 1

    await _sign_in_as(client, email="delete-survive-author@example.com")
    deleted = await _delete(client, module["id"])
    assert deleted.status_code == 200

    remaining_assignments = (
        await db_session.execute(
            select(Assignment).where(
                Assignment.translation_group_id == uuid.UUID(group_id)
            )
        )
    ).scalars().all()
    assert remaining_assignments == []

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(ModuleProgress.user_id == learner.id)
        )
    ).scalar_one()
    # The deletion of the assignment must not cascade into the learner's own
    # record of what they did.
    assert progress.completed_at is not None
    assert progress.completed_version_number == 1
    assert progress.translation_group_id == uuid.UUID(group_id)


async def test_a_learner_mid_module_sees_it_as_unavailable_once_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-midmodule-author@example.com"
    )
    group_id = module["translation_group_id"]

    learner = await _become_learner(
        client, db_session, email="delete-midmodule-learner@example.com"
    )
    opened = await _open(client, group_id)
    assert opened.status_code == 200
    page_id = opened.json()["pages"][0]["id"]
    viewed = await client.post(f"/api/me/modules/{group_id}/pages/{page_id}/view")
    assert viewed.status_code == 200

    await _sign_in_as(client, email="delete-midmodule-author@example.com")
    assert (await _delete(client, module["id"])).status_code == 200

    await _sign_in_as(client, email="delete-midmodule-learner@example.com")
    reopened = await _open(client, group_id)
    assert reopened.status_code == 404
    assert reopened.json()["detail"]["code"] == "module_unavailable"

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(ModuleProgress.user_id == learner.id)
        )
    ).scalar_one()
    assert progress.started_at is not None
    assert page_id in progress.pages_viewed


async def test_a_completion_renders_with_the_tombstoned_title_in_my_learning(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client,
        db_session,
        email="delete-mylearning-author@example.com",
        title="Data Protection Basics",
    )
    group_id = module["translation_group_id"]

    await _become_learner(client, db_session, email="delete-mylearning-learner@example.com")
    completion = await _complete(client, group_id)
    assert completion["completed_version_number"] == 1

    await _sign_in_as(client, email="delete-mylearning-author@example.com")
    assert (await _delete(client, module["id"])).status_code == 200

    await _sign_in_as(client, email="delete-mylearning-learner@example.com")
    mine = await client.get("/api/me/modules")
    assert mine.status_code == 200
    rows = [row for row in mine.json() if row["translation_group_id"] == group_id]
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Data Protection Basics"
    assert row["completed_version_number"] == 1
    assert row["completed_at"] is not None
    # No longer reachable to read again, but the record of having read it
    # stands.
    assert row["available"] is False


async def test_a_completion_renders_in_the_administrator_report_after_delete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-report-author@example.com"
    )
    group_id = module["translation_group_id"]

    group = Group(name="Delete-report group")
    db_session.add(group)
    await db_session.commit()
    assigned = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert assigned.status_code == 201

    learner = await _become_learner(
        client, db_session, email="delete-report-learner@example.com"
    )
    await db_session.refresh(learner, attribute_names=["groups"])
    learner.groups.append(group)
    await db_session.commit()
    await _complete(client, group_id)

    await _sign_in_as(client, email="delete-report-author@example.com")
    assert (await _delete(client, module["id"])).status_code == 200

    admin = await _login_with_role(
        client, db_session, email="delete-report-admin@example.com", role_name="Administrator"
    )
    report = await client.get(f"/api/content/modules/{module['id']}/report")
    assert report.status_code == 200
    body = report.json()
    matching = [row for row in body["learners"] if row["user_id"] == str(learner.id)]
    assert len(matching) == 1
    assert matching[0]["state"] == "completed"
    assert matching[0]["completed_version_number"] == 1
    del admin


async def test_only_a_content_manager_or_administrator_may_delete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _published_module_with_page(
        client, db_session, email="delete-perms-author@example.com"
    )
    await _become_learner(client, db_session, email="delete-perms-learner@example.com")

    response = await _delete(client, module["id"])
    assert response.status_code == 403


async def test_deleting_one_variant_removes_the_shared_assignment_for_every_sibling(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pinned deliberately, not merely allowed to happen: an assignment
    targets a translation group, not a single language's text (ticket 7), so
    "its assignments are removed" (ticket 11) removes the group's one shared
    assignment — un-assigning a surviving sibling variant too, even though
    that sibling's own pages, versions, and assets are untouched. Ticket 11
    does not special-case a multi-variant group; this is what its literal
    wording does when applied to one."""
    await _login_with_role(
        client, db_session, email="delete-sibling-author@example.com", role_name="Content Manager"
    )
    en_id = await _make_module(client, title="Phishing Awareness", language="en")
    await _add_page(client, en_id)
    en = await _publish(client, en_id)
    group_id = en["translation_group_id"]

    de_id = await _make_module(client, title="Phishing-Bewusstsein", language="de")
    await _add_page(client, de_id)
    de = await _publish(client, de_id)

    linked = await client.post(
        f"/api/content/translation-groups/{group_id}/variants",
        json={"module_id": de_id},
    )
    assert linked.status_code == 201, linked.text

    group = Group(name="Delete-sibling group")
    db_session.add(group)
    await db_session.commit()
    assigned = await client.post(
        f"/api/content/modules/{en_id}/assignments",
        json={"target_type": "group", "target_id": str(group.id), "requirement": "mandatory"},
    )
    assert assigned.status_code == 201

    deleted = await _delete(client, en_id)
    assert deleted.status_code == 200

    remaining_assignments = (
        await db_session.execute(
            select(Assignment).where(Assignment.translation_group_id == uuid.UUID(group_id))
        )
    ).scalars().all()
    assert remaining_assignments == []

    # The surviving sibling's own material is completely untouched.
    de_pages = (
        await db_session.execute(select(ModulePage).where(ModulePage.module_id == uuid.UUID(de_id)))
    ).scalars().all()
    de_module = await db_session.get(Module, uuid.UUID(de_id))
    assert len(de_pages) == 1
    assert de_module is not None
    assert de_module.status == "published"
    del de

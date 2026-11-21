"""Campaign drafts (Release 2, ticket 1).

What this file holds down: a campaign belongs to its creator and is a 404 —
never a 403 — to everyone else on every route; naming a person is an
Administrator's act; and a draft may reference unpublished or deleted material
but says so per module rather than hiding it.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from tests.test_assignments import (
    _create_module,
    _login,
    _login_with_role,
    _make_group,
    _make_user_with_role,
)


async def _as(client: AsyncClient, db: AsyncSession, email: str, role: str) -> Any:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db, email=email, role_name=role)


async def _new_campaign(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Phishing programme", **overrides}
    response = await client.post("/api/content/campaigns", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _module_group(
    client: AsyncClient, db: AsyncSession, *, email: str, title: str, publish: bool = True
) -> str:
    module = await _create_module(
        client, db, author_email=email, title=title, publish=publish
    )
    return module["translation_group_id"]


# --- Creating and reading ---------------------------------------------------


async def test_a_content_manager_creates_a_draft_with_modules_and_group_targets(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _module_group(client, db_session, email="camp-a1@example.com", title="Basics")
    second = await _module_group(client, db_session, email="camp-a2@example.com", title="Advanced")
    group = await _make_group(db_session, name="Finance")
    creator = await _as(client, db_session, "camp-a-cm@example.com", "Content Manager")

    response = await client.post(
        "/api/content/campaigns",
        json={
            "name": "Phishing programme",
            "description": "Five short modules",
            "start_date": "2026-11-01",
            "due_date": "2026-12-01",
            "auto_reminders": False,
            "sequential": True,
            "modules": [
                {"translation_group_id": second, "requirement": "recommended"},
                {"translation_group_id": first, "requirement": "mandatory"},
            ],
            "targets": [{"type": "group", "id": str(group.id)}],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["created_by"]["id"] == str(creator.id)
    assert body["sequential"] is True
    assert body["auto_reminders"] is False
    assert [(m["title"], m["requirement"], m["position"]) for m in body["modules"]] == [
        ("Advanced", "recommended", 0),
        ("Basics", "mandatory", 1),
    ]
    assert body["targets"] == [{"type": "group", "id": str(group.id), "name": "Finance"}]

    fetched = await client.get(f"/api/content/campaigns/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["modules"] == body["modules"]


async def test_created_by_and_status_cannot_be_smuggled_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _as(client, db_session, "camp-smuggle@example.com", "Content Manager")
    for extra in ({"created_by": str(uuid.uuid4())}, {"status": "active"}):
        response = await client.post("/api/content/campaigns", json={"name": "X", **extra})
        assert response.status_code == 422


async def test_validation_rejects_bad_input(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group = await _module_group(client, db_session, email="camp-val-a@example.com", title="One")
    await _as(client, db_session, "camp-val@example.com", "Content Manager")

    empty = await client.post("/api/content/campaigns", json={"name": ""})
    assert empty.status_code == 422
    backwards = await client.post(
        "/api/content/campaigns",
        json={"name": "X", "start_date": "2026-12-01", "due_date": "2026-11-01"},
    )
    assert backwards.status_code == 422
    duplicate = await client.post(
        "/api/content/campaigns",
        json={
            "name": "X",
            "modules": [
                {"translation_group_id": group, "requirement": "mandatory"},
                {"translation_group_id": group, "requirement": "recommended"},
            ],
        },
    )
    assert duplicate.status_code == 422
    bad_requirement = await client.post(
        "/api/content/campaigns",
        json={"name": "X", "modules": [{"translation_group_id": group, "requirement": "maybe"}]},
    )
    assert bad_requirement.status_code == 422
    unknown_module = await client.post(
        "/api/content/campaigns",
        json={
            "name": "X",
            "modules": [{"translation_group_id": str(uuid.uuid4()), "requirement": "mandatory"}],
        },
    )
    assert unknown_module.status_code == 404
    unknown_group = await client.post(
        "/api/content/campaigns",
        json={"name": "X", "targets": [{"type": "group", "id": str(uuid.uuid4())}]},
    )
    assert unknown_group.status_code == 404


async def test_a_learner_cannot_use_any_campaign_route(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _as(client, db_session, "camp-owner-l@example.com", "Content Manager")
    campaign = await _new_campaign(client)
    await _as(client, db_session, "camp-learner@example.com", "Learner")

    assert (await client.get("/api/content/campaigns")).status_code == 403
    assert (await client.post("/api/content/campaigns", json={"name": "X"})).status_code == 403
    assert (await client.get(f"/api/content/campaigns/{campaign['id']}")).status_code == 403
    assert (
        await client.patch(f"/api/content/campaigns/{campaign['id']}", json={"name": "Y"})
    ).status_code == 403


async def test_an_unauthenticated_caller_is_refused(client: AsyncClient) -> None:
    client.cookies.clear()
    assert (await client.get("/api/content/campaigns")).status_code in (401, 403)


# --- Visibility: 404, never 403 --------------------------------------------


async def test_other_content_managers_get_404_on_every_route(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _as(client, db_session, "camp-vis-owner@example.com", "Content Manager")
    campaign = await _new_campaign(client, name="Owner only")
    url = f"/api/content/campaigns/{campaign['id']}"

    await _as(client, db_session, "camp-vis-other-cm@example.com", "Content Manager")
    assert (await client.get(url)).status_code == 404
    assert (await client.patch(url, json={"name": "Hijack"})).status_code == 404
    assert (await client.get("/api/content/campaigns")).json() == []

    await _login(client, email="camp-vis-owner@example.com")
    assert (await client.get(url)).json()["name"] == "Owner only"


async def test_the_list_shows_only_my_campaigns(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _as(client, db_session, "camp-list-a@example.com", "Content Manager")
    await _new_campaign(client, name="Mine")
    await _as(client, db_session, "camp-list-b@example.com", "Content Manager")
    await _new_campaign(client, name="Theirs")

    listing = (await client.get("/api/content/campaigns")).json()
    assert [c["name"] for c in listing] == ["Theirs"]
    assert listing[0]["status"] == "draft"
    assert listing[0]["module_count"] == 0


# --- Targets ----------------------------------------------------------------


async def test_an_individual_target_is_a_403_for_a_content_manager(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    person = await _make_user_with_role(db_session, email="camp-person@example.com", role_name="Learner")
    await _as(client, db_session, "camp-ind-cm@example.com", "Content Manager")

    created = await client.post(
        "/api/content/campaigns",
        json={"name": "X", "targets": [{"type": "user", "id": str(person.id)}]},
    )
    assert created.status_code == 403

    campaign = await _new_campaign(client)
    patched = await client.patch(
        f"/api/content/campaigns/{campaign['id']}",
        json={"targets": [{"type": "user", "id": str(person.id)}]},
    )
    assert patched.status_code == 403


async def test_an_administrator_may_target_an_individual_and_sees_their_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    person = await _make_user_with_role(db_session, email="camp-ind2@example.com", role_name="Learner")
    await _as(client, db_session, "camp-ind-admin@example.com", "Administrator")

    campaign = await _new_campaign(client, targets=[{"type": "user", "id": str(person.id)}])
    assert campaign["targets"][0]["type"] == "user"
    assert campaign["targets"][0]["name"] == "Lena Learner"

    # And may later strip them out again.
    cleared = await client.patch(f"/api/content/campaigns/{campaign['id']}", json={"targets": []})
    assert cleared.status_code == 200
    assert cleared.json()["targets"] == []


async def test_a_content_manager_cannot_strip_an_individual_target(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # An Administrator's individual target on a Content Manager's campaign;
    # simulated by writing the target row directly.
    from app.models import CampaignTarget

    person = await _make_user_with_role(db_session, email="camp-strip@example.com", role_name="Learner")
    await _as(client, db_session, "camp-strip-cm@example.com", "Content Manager")
    campaign = await _new_campaign(client)
    db_session.add(
        CampaignTarget(
            campaign_id=uuid.UUID(campaign["id"]), target_type="user", target_id=person.id
        )
    )
    await db_session.commit()

    response = await client.patch(f"/api/content/campaigns/{campaign['id']}", json={"targets": []})
    assert response.status_code == 403


async def test_group_targets_can_be_added_and_removed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    one = await _make_group(db_session, name="Camp Group One")
    two = await _make_group(db_session, name="Camp Group Two")
    await _as(client, db_session, "camp-tgt@example.com", "Content Manager")
    campaign = await _new_campaign(client, targets=[{"type": "group", "id": str(one.id)}])
    url = f"/api/content/campaigns/{campaign['id']}"

    swapped = await client.patch(
        url,
        json={"targets": [{"type": "group", "id": str(two.id)}]},
    )
    assert [t["name"] for t in swapped.json()["targets"]] == ["Camp Group Two"]

    both = await client.patch(
        url,
        json={
            "targets": [
                {"type": "group", "id": str(one.id)},
                {"type": "group", "id": str(two.id)},
            ]
        },
    )
    assert len(both.json()["targets"]) == 2


async def test_content_groups_listing_is_counts_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_group(db_session, name="Counts Only Group")
    await _as(client, db_session, "camp-groups@example.com", "Content Manager")
    rows = (await client.get("/api/content/groups")).json()
    assert rows
    assert set(rows[0]) == {"id", "name", "description", "member_count"}


# --- Modules: ordering, requirement, availability ---------------------------


async def test_modules_can_be_reordered_and_their_requirement_changed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _module_group(client, db_session, email="camp-ord-a@example.com", title="Alpha")
    b = await _module_group(client, db_session, email="camp-ord-b@example.com", title="Beta")
    c = await _module_group(client, db_session, email="camp-ord-c@example.com", title="Gamma")
    await _as(client, db_session, "camp-ord@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        modules=[
            {"translation_group_id": a, "requirement": "mandatory"},
            {"translation_group_id": b, "requirement": "mandatory"},
        ],
    )
    url = f"/api/content/campaigns/{campaign['id']}"

    patched = await client.patch(
        url,
        json={
            "modules": [
                {"translation_group_id": b, "requirement": "mandatory"},
                {"translation_group_id": c, "requirement": "recommended"},
                {"translation_group_id": a, "requirement": "recommended"},
            ]
        },
    )

    assert patched.status_code == 200, patched.text
    assert [(m["title"], m["requirement"]) for m in patched.json()["modules"]] == [
        ("Beta", "mandatory"),
        ("Gamma", "recommended"),
        ("Alpha", "recommended"),
    ]

    dropped = await client.patch(url, json={"modules": []})
    assert dropped.json()["modules"] == []


async def test_unpublished_and_deleted_modules_are_allowed_but_reported(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    live = await _module_group(client, db_session, email="camp-av-a@example.com", title="Live")
    draft = await _module_group(
        client, db_session, email="camp-av-b@example.com", title="Draft one", publish=False
    )
    gone = await _create_module(
        client, db_session, author_email="camp-av-c@example.com", title="Soon gone"
    )
    deleted = await client.delete(f"/api/content/modules/{gone['id']}")
    assert deleted.status_code == 200, deleted.text

    await _as(client, db_session, "camp-av@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        modules=[
            {"translation_group_id": live, "requirement": "mandatory"},
            {"translation_group_id": draft, "requirement": "mandatory"},
            {"translation_group_id": gone["translation_group_id"], "requirement": "recommended"},
        ],
    )

    assert [(m["title"], m["availability"]) for m in campaign["modules"]] == [
        ("Live", "published"),
        ("Draft one", "unpublished"),
        ("Soon gone", "deleted"),
    ]


async def test_a_translation_added_later_is_covered_by_the_group_reference(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group = await _module_group(client, db_session, email="camp-tr@example.com", title="Original")
    await _as(client, db_session, "camp-tr-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client, modules=[{"translation_group_id": group, "requirement": "mandatory"}]
    )
    # The campaign names the group, not a module id, so it needs no rewrite.
    assert campaign["modules"][0]["translation_group_id"] == group


# --- Draft is inert, partial updates, audit ---------------------------------


async def test_a_draft_sends_no_email_and_is_not_a_learner_route(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    group = await _make_group(db_session, name="Inert Group")
    member = await _make_user_with_role(db_session, email="camp-inert@example.com", role_name="Learner")
    await db_session.refresh(member, attribute_names=["groups"])
    member.groups.append(group)
    await db_session.commit()
    module = await _module_group(client, db_session, email="camp-inert-a@example.com", title="Hidden")
    await _as(client, db_session, "camp-inert-cm@example.com", "Content Manager")
    sent_emails.clear()

    await _new_campaign(
        client,
        modules=[{"translation_group_id": module, "requirement": "mandatory"}],
        targets=[{"type": "group", "id": str(group.id)}],
    )

    assert sent_emails == []
    await _login(client, email="camp-inert@example.com")
    mine = await client.get("/api/me/modules")
    assert mine.json() == []


async def test_patch_is_partial_and_dates_can_be_cleared(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _as(client, db_session, "camp-patch@example.com", "Content Manager")
    campaign = await _new_campaign(
        client, description="d", start_date="2026-11-01", due_date="2026-12-01"
    )
    url = f"/api/content/campaigns/{campaign['id']}"

    renamed = (await client.patch(url, json={"name": "Renamed"})).json()
    assert renamed["name"] == "Renamed"
    assert renamed["description"] == "d"
    assert renamed["due_date"] == "2026-12-01"

    cleared = (await client.patch(url, json={"due_date": None})).json()
    assert cleared["due_date"] is None
    assert cleared["start_date"] == "2026-11-01"

    clash = await client.patch(url, json={"due_date": "2026-10-01"})
    assert clash.status_code == 422

    for bad in ({"name": None}, {"sequential": None}, {"modules": None}, {"targets": None}, {"status": "active"}, {"created_by": str(uuid.uuid4())}):
        assert (await client.patch(url, json=bad)).status_code == 422


async def test_create_and_update_are_audit_logged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    creator = await _as(client, db_session, "camp-audit@example.com", "Content Manager")
    campaign = await _new_campaign(client, name="Audited")
    await client.patch(f"/api/content/campaigns/{campaign['id']}", json={"name": "Audited 2"})
    # A no-op patch records nothing.
    await client.patch(f"/api/content/campaigns/{campaign['id']}", json={"name": "Audited 2"})

    entries = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.actor_user_id == creator.id)
                .where(AuditLog.action.in_(["campaign_created", "campaign_updated"]))
                .order_by(AuditLog.timestamp)
            )
        )
        .scalars()
        .all()
    )
    assert [e.action for e in entries] == ["campaign_created", "campaign_updated"]
    assert entries[0].detail["campaign_id"] == campaign["id"]
    assert entries[1].detail["changed"] == ["name"]


async def test_a_modules_only_edit_bumps_updated_at_and_the_list_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group = await _module_group(client, db_session, email="camp-ts-a@example.com", title="Stamp")
    await _as(client, db_session, "camp-ts@example.com", "Content Manager")
    first = await _new_campaign(client, name="First")
    await _new_campaign(client, name="Second")

    patched = await client.patch(
        f"/api/content/campaigns/{first['id']}",
        json={"modules": [{"translation_group_id": group, "requirement": "mandatory"}]},
    )

    assert patched.json()["updated_at"] > first["updated_at"]
    listing = (await client.get("/api/content/campaigns")).json()
    assert [c["name"] for c in listing] == ["First", "Second"]

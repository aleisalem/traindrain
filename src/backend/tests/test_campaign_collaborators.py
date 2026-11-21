"""Campaign collaborators, Administrator reach and presence (Release 2, ticket 2).

The permission matrix: creator and Administrator manage people and delete
drafts; a collaborator edits but does neither (403); a non-participant gets a
404 on everything.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from tests.test_assignments import _make_user_with_role
from tests.test_campaigns import _as, _new_campaign

ADD = "/api/content/campaigns/{}/collaborators"


async def _setup(
    client: AsyncClient, db: AsyncSession, tag: str
) -> tuple[dict[str, Any], str]:
    """A campaign owned by `{tag}-owner`, with `{tag}-collab` added; the other
    people (`-outsider`, `-admin`, `-learner`) exist. Leaves the owner logged in."""
    await _make_user_with_role(db, email=f"{tag}-collab@example.com", role_name="Content Manager")
    await _make_user_with_role(db, email=f"{tag}-outsider@example.com", role_name="Content Manager")
    await _make_user_with_role(db, email=f"{tag}-admin@example.com", role_name="Administrator")
    await _make_user_with_role(db, email=f"{tag}-learner@example.com", role_name="Learner")
    await _as(client, db, f"{tag}-owner@example.com", "Content Manager")
    campaign = await _new_campaign(client, name="Shared")
    response = await client.post(
        ADD.format(campaign["id"]), json={"email": f"{tag}-collab@example.com"}
    )
    assert response.status_code == 201, response.text
    return response.json(), campaign["id"]


async def _login_as(client: AsyncClient, email: str) -> None:
    from tests.test_assignments import _login

    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=email)


async def test_creator_adds_a_collaborator_who_then_sees_and_edits_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body, cid = await _setup(client, db_session, "cc1")
    assert [c["display_name"] for c in body["collaborators"]] == ["Lena Learner"]
    assert body["can_manage"] is True

    await _login_as(client, "cc1-collab@example.com")
    url = f"/api/content/campaigns/{cid}"
    fetched = (await client.get(url)).json()
    assert fetched["can_manage"] is False
    assert [c["id"] for c in (await client.get("/api/content/campaigns")).json()] == [cid]
    edited = await client.patch(url, json={"name": "Renamed", "due_date": "2027-01-01"})
    assert edited.status_code == 200 and edited.json()["name"] == "Renamed"


async def test_collaborator_must_hold_an_authoring_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, cid = await _setup(client, db_session, "cc2")
    learner = await client.post(ADD.format(cid), json={"email": "cc2-learner@example.com"})
    assert learner.status_code == 409
    unknown = await client.post(ADD.format(cid), json={"email": "nobody@example.com"})
    assert unknown.status_code == 404
    dup = await client.post(ADD.format(cid), json={"email": "cc2-collab@example.com"})
    assert dup.status_code == 409
    self_add = await client.post(ADD.format(cid), json={"email": "cc2-owner@example.com"})
    assert self_add.status_code == 409


async def test_a_collaborator_cannot_manage_people_or_delete_but_a_stranger_gets_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, cid = await _setup(client, db_session, "cc3")
    base = f"/api/content/campaigns/{cid}"
    other = await _make_user_with_role(
        db_session, email="cc3-other@example.com", role_name="Content Manager"
    )

    await _login_as(client, "cc3-collab@example.com")
    assert (await client.post(ADD.format(cid), json={"email": "cc3-other@example.com"})).status_code == 403
    assert (await client.delete(f"{base}/collaborators/{other.id}")).status_code == 403
    assert (await client.delete(base)).status_code == 403
    assert (await client.post(f"{base}/owner", json={"user_id": str(other.id)})).status_code == 403

    await _login_as(client, "cc3-outsider@example.com")
    assert (await client.post(ADD.format(cid), json={"email": "cc3-other@example.com"})).status_code == 404
    assert (await client.delete(f"{base}/collaborators/{other.id}")).status_code == 404
    assert (await client.delete(base)).status_code == 404
    assert (await client.post(f"{base}/owner", json={"user_id": str(other.id)})).status_code == 404
    assert (await client.post(f"{base}/editing")).status_code == 404

    await _login_as(client, "cc3-learner@example.com")
    assert (await client.post(ADD.format(cid), json={"email": "cc3-other@example.com"})).status_code == 403


async def test_removing_a_collaborator_cuts_their_access(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body, cid = await _setup(client, db_session, "cc4")
    collab_id = body["collaborators"][0]["id"]
    removed = await client.delete(f"/api/content/campaigns/{cid}/collaborators/{collab_id}")
    assert removed.status_code == 200 and removed.json()["collaborators"] == []
    again = await client.delete(f"/api/content/campaigns/{cid}/collaborators/{collab_id}")
    assert again.status_code == 404

    await _login_as(client, "cc4-collab@example.com")
    assert (await client.get(f"/api/content/campaigns/{cid}")).status_code == 404


async def test_draft_deletion_by_creator_and_administrator_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, cid = await _setup(client, db_session, "cc5")
    assert (await client.delete(f"/api/content/campaigns/{cid}")).status_code == 204
    assert (await client.get(f"/api/content/campaigns/{cid}")).status_code == 404

    second = (await _new_campaign(client, name="Second"))["id"]
    await _login_as(client, "cc5-admin@example.com")
    assert (await client.delete(f"/api/content/campaigns/{second}")).status_code == 204


async def test_only_a_draft_can_be_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import Campaign

    _, cid = await _setup(client, db_session, "cc6")
    campaign = await db_session.get(Campaign, uuid.UUID(cid))
    assert campaign is not None
    campaign.status = "active"
    await db_session.commit()
    assert (await client.delete(f"/api/content/campaigns/{cid}")).status_code == 409


async def test_an_administrator_sees_edits_and_targets_individuals_on_any_campaign(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, cid = await _setup(client, db_session, "cc7")
    person = await _make_user_with_role(db_session, email="cc7-p@example.com", role_name="Learner")
    await _login_as(client, "cc7-admin@example.com")

    listing = (await client.get("/api/content/campaigns")).json()
    assert cid in [c["id"] for c in listing]
    url = f"/api/content/campaigns/{cid}"
    patched = await client.patch(
        url, json={"name": "Admin edit", "targets": [{"type": "user", "id": str(person.id)}]}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["targets"][0]["name"] == "Lena Learner"
    assert patched.json()["can_manage"] is True

    # A collaborator may neither add nor strip an individual.
    await _login_as(client, "cc7-collab@example.com")
    stripped = await client.patch(url, json={"targets": []})
    assert stripped.status_code == 403


async def test_administrator_reassigns_the_creator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body, cid = await _setup(client, db_session, "cc8")
    collab_id = body["collaborators"][0]["id"]
    learner = await _make_user_with_role(
        db_session, email="cc8-l2@example.com", role_name="Learner"
    )
    await _login_as(client, "cc8-admin@example.com")
    url = f"/api/content/campaigns/{cid}/owner"

    assert (await client.post(url, json={"user_id": str(learner.id)})).status_code == 409
    assert (await client.post(url, json={"user_id": str(uuid.uuid4())})).status_code == 404

    reassigned = await client.post(url, json={"user_id": collab_id})
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["created_by"]["id"] == collab_id
    assert reassigned.json()["collaborators"] == []
    assert (await client.post(url, json={"user_id": collab_id})).status_code == 409

    # The previous creator is no longer a participant.
    await _login_as(client, "cc8-owner@example.com")
    assert (await client.get(f"/api/content/campaigns/{cid}")).status_code == 404


async def test_collaborators_survive_an_erased_or_demoted_creator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from datetime import UTC, datetime

    from app.models import Campaign, User

    body, cid = await _setup(client, db_session, "cc9")
    campaign = await db_session.get(Campaign, uuid.UUID(cid))
    assert campaign is not None
    creator = await db_session.get(User, campaign.created_by)
    assert creator is not None
    creator.erased_at = datetime.now(UTC)
    creator.roles = []
    await db_session.commit()

    await _login_as(client, "cc9-collab@example.com")
    assert (await client.get(f"/api/content/campaigns/{cid}")).status_code == 200
    # …and an Administrator can hand it to a living creator.
    await _login_as(client, "cc9-admin@example.com")
    ok = await client.post(
        f"/api/content/campaigns/{cid}/owner", json={"user_id": body["collaborators"][0]["id"]}
    )
    assert ok.status_code == 200


async def test_presence_shows_the_other_editor_and_clears_on_leave(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, cid = await _setup(client, db_session, "cc10")
    url = f"/api/content/campaigns/{cid}/editing"
    assert (await client.post(url)).json() == {"editors": []}

    await _login_as(client, "cc10-collab@example.com")
    seen = (await client.post(url)).json()["editors"]
    assert [e["display_name"] for e in seen] == ["Lena Learner"]

    await _login_as(client, "cc10-owner@example.com")
    assert len((await client.post(url)).json()["editors"]) == 1
    await _login_as(client, "cc10-collab@example.com")
    assert (await client.delete(url)).status_code == 204
    await _login_as(client, "cc10-owner@example.com")
    assert (await client.post(url)).json() == {"editors": []}


async def test_collaborator_and_ownership_changes_are_audit_logged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body, cid = await _setup(client, db_session, "cc11")
    collab_id = body["collaborators"][0]["id"]
    await client.delete(f"/api/content/campaigns/{cid}/collaborators/{collab_id}")
    await _login_as(client, "cc11-admin@example.com")
    await client.post(f"/api/content/campaigns/{cid}/owner", json={"user_id": collab_id})
    await client.delete(f"/api/content/campaigns/{cid}")

    actions = set(
        (
            await db_session.execute(
                select(AuditLog.action).where(AuditLog.action.like("campaign_%"))
            )
        ).scalars()
    )
    assert {
        "campaign_collaborator_added",
        "campaign_collaborator_removed",
        "campaign_owner_changed",
        "campaign_deleted",
    } <= actions

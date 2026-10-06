"""Campaign suspend and resume (Release 2, ticket 4).

What this file holds down: suspension removes only the campaign's own route to
a module (a catalog or direct-assignment route survives; with none, the module
is a 404 and leaves "my learning"), progress is kept, resume past the due date
succeeds but flags the lapse until an author sets a later date, and every
transition is audited and refused when it does not fit.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Module
from tests.test_assignments import (
    _add_to_group,
    _login,
    _make_group,
    _make_user_with_role,
    _switch_to,
)
from tests.test_campaign_activation import _campaign, _read_all_and_complete
from tests.test_campaigns import _as

BASE = "/api/content/campaigns"


async def _audit(db: AsyncSession, action: str, campaign_id: str) -> list[AuditLog]:
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars()
    return [e for e in rows if e.detail["campaign_id"] == campaign_id]


async def _module_of(db: AsyncSession, group_id: str) -> Module:
    return (
        await db.execute(select(Module).where(Module.translation_group_id == uuid.UUID(group_id)))
    ).scalar_one()


async def _active_campaign(
    client: AsyncClient, db: AsyncSession, tag: str, **overrides: Any
) -> tuple[dict[str, Any], list[str], Any]:
    campaign, groups, group = await _campaign(client, db, tag, **overrides)
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200
    return campaign, groups, group


# --- Transitions ----------------------------------------------------------------


async def test_suspend_and_resume_move_active_to_suspended_and_back_with_audit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _active_campaign(client, db_session, "sus1")
    cid = campaign["id"]
    suspended = await client.post(f"{BASE}/{cid}/suspend")
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    resumed = await client.post(f"{BASE}/{cid}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "active"
    assert resumed.json()["due_date_lapsed"] is False
    assert len(await _audit(db_session, "campaign_suspended", cid)) == 1
    assert len(await _audit(db_session, "campaign_resumed", cid)) == 1


async def test_other_transitions_are_conflicts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _campaign(client, db_session, "sus2")
    cid = campaign["id"]
    assert (await client.post(f"{BASE}/{cid}/suspend")).status_code == 409  # draft
    assert (await client.post(f"{BASE}/{cid}/resume")).status_code == 409  # draft
    await client.post(f"{BASE}/{cid}/activate")
    assert (await client.post(f"{BASE}/{cid}/resume")).status_code == 409  # active
    await client.post(f"{BASE}/{cid}/suspend")
    assert (await client.post(f"{BASE}/{cid}/suspend")).status_code == 409  # already suspended
    assert (await client.post(f"{BASE}/{cid}/activate")).status_code == 409
    await client.post(f"{BASE}/{cid}/resume")
    await client.post(f"{BASE}/{cid}/close")
    assert (await client.post(f"{BASE}/{cid}/suspend")).status_code == 409  # closed
    assert (await client.post(f"{BASE}/{cid}/resume")).status_code == 409


async def test_collaborators_may_suspend_and_resume_but_outsiders_get_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _active_campaign(client, db_session, "sus4")
    cid = campaign["id"]
    await _make_user_with_role(db_session, email="sus4-collab@example.com", role_name="Content Manager")
    await client.post(f"{BASE}/{cid}/collaborators", json={"email": "sus4-collab@example.com"})

    await _as(client, db_session, "sus4-other@example.com", "Content Manager")
    assert (await client.post(f"{BASE}/{cid}/suspend")).status_code == 404
    assert (await client.post(f"{BASE}/{cid}/resume")).status_code == 404
    await _switch_to(client, db_session, email="sus4-learner@example.com")
    assert (await client.post(f"{BASE}/{cid}/suspend")).status_code == 403

    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="sus4-collab@example.com")
    assert (await client.post(f"{BASE}/{cid}/suspend")).status_code == 200
    assert (await client.post(f"{BASE}/{cid}/resume")).status_code == 200


# --- Access ---------------------------------------------------------------------


async def test_suspension_removes_the_only_route_and_keeps_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _active_campaign(client, db_session, "acc1", mandatory=2)
    learner = await _switch_to(client, db_session, email="acc1-l@example.com")
    await _add_to_group(db_session, learner, group)
    await _read_all_and_complete(client, groups[0])
    await _login(client, email="acc1-cm@example.com")
    assert (await client.post(f"{BASE}/{campaign['id']}/suspend")).status_code == 200

    await _login(client, email="acc1-l@example.com")
    assert (await client.get("/api/me/campaigns")).json() == []
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 404
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 404
    mine = (await client.get("/api/me/modules")).json()
    assert groups[0] not in {row["translation_group_id"] for row in mine}

    await _login(client, email="acc1-cm@example.com")
    assert (await client.post(f"{BASE}/{campaign['id']}/resume")).status_code == 200

    await _login(client, email="acc1-l@example.com")
    campaigns = (await client.get("/api/me/campaigns")).json()
    assert campaigns[0]["required_done"] == 1  # progress survived
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200


async def test_the_catalog_route_survives_suspension(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _active_campaign(client, db_session, "acc2")
    module = await _module_of(db_session, groups[0])
    module.catalog_visible = True
    await db_session.commit()
    learner = await _switch_to(client, db_session, email="acc2-l@example.com")
    await _add_to_group(db_session, learner, group)
    await _read_all_and_complete(client, groups[0])
    await _login(client, email="acc2-cm@example.com")
    await client.post(f"{BASE}/{campaign['id']}/suspend")

    await _login(client, email="acc2-l@example.com")
    assert (await client.get("/api/me/campaigns")).json() == []
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200
    mine = (await client.get("/api/me/modules")).json()
    row = next(r for r in mine if r["translation_group_id"] == groups[0])
    assert row["available"] is True


async def test_a_direct_assignment_route_survives_suspension(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _active_campaign(client, db_session, "acc3")
    other = await _make_group(db_session, name="acc3-direct")
    module = await _module_of(db_session, groups[0])
    learner = await _make_user_with_role(db_session, email="acc3-l@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)
    await _add_to_group(db_session, learner, other)

    await _login(client, email="acc3-cm@example.com")
    assigned = await client.post(
        f"/api/content/modules/{module.id}/assignments",
        json={"target_type": "group", "target_id": str(other.id), "requirement": "mandatory"},
    )
    assert assigned.status_code == 201, assigned.text
    await client.post(f"{BASE}/{campaign['id']}/suspend")

    await _login(client, email="acc3-l@example.com")
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200
    row = next(
        r for r in (await client.get("/api/me/modules")).json()
        if r["translation_group_id"] == groups[0]
    )
    assert row["requirement"] == "mandatory" and row["available"] is True


# --- Overdue and the lapsed due date ----------------------------------------------


async def test_a_suspended_campaign_is_never_overdue_for_the_learner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, group = await _active_campaign(
        client, db_session, "ovd1", due_date="2020-01-01"
    )
    learner = await _switch_to(client, db_session, email="ovd1-l@example.com")
    await _add_to_group(db_session, learner, group)
    assert (await client.get("/api/me/campaigns")).json()[0]["overdue"] is True
    await _login(client, email="ovd1-cm@example.com")
    await client.post(f"{BASE}/{campaign['id']}/suspend")
    await _login(client, email="ovd1-l@example.com")
    assert (await client.get("/api/me/campaigns")).json() == []


async def test_resuming_past_the_due_date_succeeds_and_flags_the_lapse_until_a_later_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _active_campaign(client, db_session, "lap1", due_date="2020-01-01")
    cid = campaign["id"]
    await client.post(f"{BASE}/{cid}/suspend")
    resumed = await client.post(f"{BASE}/{cid}/resume")
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "active"
    assert body["due_date"] == "2020-01-01"  # never shifted on its own
    assert body["due_date_lapsed"] is True
    audit = (await _audit(db_session, "campaign_resumed", cid))[0]
    assert audit.detail["due_date_lapsed"] is True

    # Another past date does not settle it.
    still = await client.patch(f"{BASE}/{cid}", json={"due_date": "2021-01-01"})
    assert still.json()["due_date_lapsed"] is True
    # A later date does.
    fixed = await client.patch(f"{BASE}/{cid}", json={"due_date": "2999-01-01"})
    assert fixed.status_code == 200
    assert fixed.json()["due_date_lapsed"] is False
    assert (await client.get(f"{BASE}/{cid}")).json()["due_date_lapsed"] is False


async def test_resuming_before_the_due_date_is_not_flagged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _active_campaign(client, db_session, "lap2", due_date="2999-01-01")
    await client.post(f"{BASE}/{campaign['id']}/suspend")
    resumed = await client.post(f"{BASE}/{campaign['id']}/resume")
    assert resumed.json()["due_date_lapsed"] is False


async def test_clearing_the_due_date_settles_the_lapse(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _active_campaign(client, db_session, "lap3", due_date="2020-01-01")
    cid = campaign["id"]
    await client.post(f"{BASE}/{cid}/suspend")
    await client.post(f"{BASE}/{cid}/resume")
    cleared = await client.patch(f"{BASE}/{cid}", json={"due_date": None})
    assert cleared.json()["due_date_lapsed"] is False

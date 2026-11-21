"""Active-campaign edit safeguards (Release 2, ticket 6).

What this file holds down: adding to a running campaign just works (live on the
learner's next read, no retroactive email); removing a module or target that has
learner progress is refused until the author confirms, after an impact endpoint
has told them the number; a campaign that ever went live is never deletable;
and a module deleted elsewhere stays in the campaign as an unopenable marker
that no longer counts toward completion.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Module, ModuleProgress
from tests.test_assignments import _add_to_group, _login, _make_group, _switch_to
from tests.test_campaign_activation import _campaign, _read_all_and_complete
from tests.test_campaigns import _as, _module_group

BASE = "/api/content/campaigns"


async def _relogin(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=email)


def _mods(*groups: str) -> list[dict[str, str]]:
    return [{"translation_group_id": g, "requirement": "mandatory"} for g in groups]


async def _running(
    client: AsyncClient, db: AsyncSession, tag: str, *, mandatory: int = 2
) -> tuple[dict[str, Any], list[str], Any]:
    campaign, groups, group = await _campaign(client, db, tag, mandatory=mandatory)
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200
    return campaign, groups, group


async def _started_learner(
    client: AsyncClient, db: AsyncSession, email: str, group: Any, module_group: str, *, complete: bool
) -> Any:
    learner = await _switch_to(client, db, email=email)
    await _add_to_group(db, learner, group)
    if complete:
        await _read_all_and_complete(client, module_group)
    else:
        pages = (await client.get(f"/api/me/modules/{module_group}")).json()["pages"]
        await client.post(f"/api/me/modules/{module_group}/pages/{pages[0]['id']}/view")
    return learner


# --- Additions ------------------------------------------------------------------


async def test_adding_a_module_and_a_target_reaches_learners_on_their_next_read_without_email(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, groups, _ = await _running(client, db_session, "es1", mandatory=1)
    extra_module = await _module_group(client, db_session, email="es1-x@example.com", title="es1 extra")
    late_group = await _make_group(db_session, name="es1-late")
    late = await _switch_to(client, db_session, email="es1-late@example.com")
    await _add_to_group(db_session, late, late_group)
    assert (await client.get(f"/api/me/modules/{extra_module}")).status_code == 404

    await _relogin(client, "es1-cm@example.com")
    sent_emails.clear()
    response = await client.patch(
        f"{BASE}/{campaign['id']}",
        json={
            "modules": _mods(groups[0], extra_module),
            "targets": [
                *[{"type": t["type"], "id": t["id"]} for t in campaign["targets"]],
                {"type": "group", "id": str(late_group.id)},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert sent_emails == []

    await _relogin(client, "es1-late@example.com")
    assert (await client.get(f"/api/me/modules/{extra_module}")).status_code == 200
    mine = (await client.get("/api/me/campaigns")).json()
    assert [m["translation_group_id"] for m in mine[0]["modules"]] == [groups[0], extra_module]


# --- Impact and confirmation ------------------------------------------------------


async def test_impact_counts_learners_and_records_for_a_removed_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _running(client, db_session, "es2")
    await _started_learner(client, db_session, "es2-a@example.com", group, groups[1], complete=True)
    await _started_learner(client, db_session, "es2-b@example.com", group, groups[1], complete=False)
    await _started_learner(client, db_session, "es2-c@example.com", group, groups[0], complete=False)

    await _relogin(client, "es2-cm@example.com")
    impact = await client.post(
        f"{BASE}/{campaign['id']}/edit-impact", json={"modules": _mods(groups[0])}
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert (body["learners"], body["records"], body["completed"]) == (2, 2, 1)
    assert body["requires_confirmation"] is True
    assert body["modules"][0]["translation_group_id"] == groups[1]
    assert body["modules"][0]["records"] == 2

    # Nothing changed: it is a preview.
    again = await client.get(f"{BASE}/{campaign['id']}")
    assert len(again.json()["modules"]) == 2


async def test_removing_a_module_with_progress_needs_confirmation_and_is_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _running(client, db_session, "es3")
    learner = await _started_learner(client, db_session, "es3-a@example.com", group, groups[1], complete=True)
    await _relogin(client, "es3-cm@example.com")
    url = f"{BASE}/{campaign['id']}"

    refused = await client.patch(url, json={"modules": _mods(groups[0])})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "impact_confirmation_required"
    assert (detail["learners"], detail["records"]) == (1, 1)
    assert len((await client.get(url)).json()["modules"]) == 2

    ok = await client.patch(url, json={"modules": _mods(groups[0]), "confirm_impact": True})
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["modules"]) == 1

    # The learner's own record is untouched.
    rows = (
        await db_session.execute(select(ModuleProgress).where(ModuleProgress.user_id == learner.id))
    ).scalars().all()
    assert len(rows) == 1 and rows[0].completed_at is not None
    entry = [
        e
        for e in (
            await db_session.execute(select(AuditLog).where(AuditLog.action == "campaign_updated"))
        ).scalars()
        if e.detail["campaign_id"] == campaign["id"] and "confirmed_impact" in e.detail
    ]
    assert len(entry) == 1 and entry[0].detail["confirmed_impact"]["records"] == 1


async def test_removing_a_module_nobody_has_started_needs_no_confirmation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _running(client, db_session, "es4")
    await _started_learner(client, db_session, "es4-a@example.com", group, groups[0], complete=False)
    await _relogin(client, "es4-cm@example.com")
    url = f"{BASE}/{campaign['id']}"
    preview = (await client.post(f"{url}/edit-impact", json={"modules": _mods(groups[0])})).json()
    assert preview["records"] == 0 and preview["requires_confirmation"] is False
    assert (await client.patch(url, json={"modules": _mods(groups[0])})).status_code == 200


async def test_removing_a_target_counts_only_learners_no_longer_reached(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _running(client, db_session, "es5")
    other = await _make_group(db_session, name="es5-other")
    # Reached by both groups: stays targeted when `group` goes.
    both = await _started_learner(client, db_session, "es5-both@example.com", group, groups[0], complete=False)
    await _add_to_group(db_session, both, other)
    await _started_learner(client, db_session, "es5-only@example.com", group, groups[0], complete=False)

    await _relogin(client, "es5-cm@example.com")
    url = f"{BASE}/{campaign['id']}"
    kept = [{"type": "group", "id": str(other.id)}]
    # `other` must be a target first for "both" to stay reached.
    assert (
        await client.patch(
            url, json={"targets": [{"type": "group", "id": str(group.id)}, *kept]}
        )
    ).status_code == 200

    impact = (await client.post(f"{url}/edit-impact", json={"targets": kept})).json()
    assert (impact["learners"], impact["records"]) == (1, 1)
    refused = await client.patch(url, json={"targets": kept})
    assert refused.status_code == 409
    assert (await client.patch(url, json={"targets": kept, "confirm_impact": True})).status_code == 200


async def test_a_draft_never_needs_confirmation_and_impact_routes_hide_other_campaigns(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, _ = await _campaign(client, db_session, "es6")
    url = f"{BASE}/{campaign['id']}"
    preview = (await client.post(f"{url}/edit-impact", json={"modules": []})).json()
    assert preview["records"] == 0
    assert (await client.patch(url, json={"modules": []})).status_code == 200

    await _as(client, db_session, "es6-stranger@example.com", "Content Manager")
    assert (await client.post(f"{url}/edit-impact", json={"modules": []})).status_code == 404
    await _switch_to(client, db_session, email="es6-learner@example.com")
    assert (await client.post(f"{url}/edit-impact", json={"modules": []})).status_code == 403


# --- Deletion ----------------------------------------------------------------------


async def test_a_draft_is_deleted_by_its_creator_but_a_campaign_that_ran_never_is(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    draft, _, _ = await _campaign(client, db_session, "es7")
    assert (await client.delete(f"{BASE}/{draft['id']}")).status_code == 204
    assert (await client.get(f"{BASE}/{draft['id']}")).status_code == 404

    ran, _, _ = await _running(client, db_session, "es8", mandatory=1)
    for transition in (None, "suspend", "close"):
        if transition == "suspend":
            assert (await client.post(f"{BASE}/{ran['id']}/suspend")).status_code == 200
            assert (await client.post(f"{BASE}/{ran['id']}/resume")).status_code == 200
        if transition == "close":
            assert (await client.post(f"{BASE}/{ran['id']}/close")).status_code == 200
        refused = await client.delete(f"{BASE}/{ran['id']}")
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "campaign_already_activated"
    await _as(client, db_session, "es8-admin@example.com", "Administrator")
    assert (await client.delete(f"{BASE}/{ran['id']}")).status_code == 409


# --- Tombstones --------------------------------------------------------------------


async def test_a_deleted_module_stays_as_an_unopenable_marker_and_stops_counting(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _running(client, db_session, "es9")
    await _started_learner(client, db_session, "es9-l@example.com", group, groups[0], complete=True)
    before = (await client.get("/api/me/campaigns")).json()[0]
    assert (before["required_total"], before["required_done"], before["complete"]) == (2, 1, False)

    module = (
        await db_session.execute(select(Module).where(Module.translation_group_id == uuid.UUID(groups[1])))
    ).scalar_one()
    await _as(client, db_session, "es9-admin@example.com", "Administrator")
    assert (await client.delete(f"/api/content/modules/{module.id}")).status_code == 200

    # Authoring view keeps reporting it as deleted.
    authoring = (await client.get(f"{BASE}/{campaign['id']}")).json()
    assert [m["availability"] for m in authoring["modules"]] == ["published", "deleted"]

    await _relogin(client, "es9-l@example.com")
    after = (await client.get("/api/me/campaigns")).json()[0]
    marker = next(m for m in after["modules"] if m["translation_group_id"] == groups[1])
    assert marker["unavailable"] is True and marker["available"] is False
    assert (after["required_total"], after["required_done"], after["complete"]) == (1, 1, True)
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 404


async def test_a_deleted_mandatory_module_is_never_overdue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _running(client, db_session, "es10", mandatory=1)
    module = (
        await db_session.execute(select(Module).where(Module.translation_group_id == uuid.UUID(groups[0])))
    ).scalar_one()
    await _as(client, db_session, "es10-admin@example.com", "Administrator")
    assert (await client.delete(f"/api/content/modules/{module.id}")).status_code == 200
    learner = await _switch_to(client, db_session, email="es10-l@example.com")
    await _add_to_group(db_session, learner, group)
    mine = (await client.get("/api/me/campaigns")).json()[0]
    assert mine["modules"][0]["unavailable"] is True and mine["modules"][0]["overdue"] is False
    assert mine["complete"] is False  # nothing left to require, so never "complete"

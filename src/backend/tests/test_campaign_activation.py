"""Campaign activation and the learner's campaign view (Release 2, ticket 3).

What this file holds down: activation is refused unless it could be honoured;
a learner's route to a campaign's modules is derived live from current group
membership (late joiner in, leaver out, progress kept); completion is computed
on every read so a substantive republish reopens it; closing stops new starts
but keeps records readable; and the daily job activates by start date exactly
once.
"""

import uuid
from datetime import date
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns import activate_due_campaigns
from app.models import AuditLog
from tests.conftest import FakeSESClient
from tests.test_assignments import (
    _add_to_group,
    _login,
    _make_group,
    _make_user_with_role,
    _remove_from_group,
    _switch_to,
)
from tests.test_campaigns import _as, _module_group, _new_campaign

BASE = "/api/content/campaigns"


async def _campaign(
    client: AsyncClient, db: AsyncSession, tag: str, *, mandatory: int = 1, **overrides: Any
) -> tuple[dict[str, Any], list[str], Any]:
    """A draft campaign by `{tag}-cm` aimed at group `{tag}`, with published modules."""
    groups = []
    for i in range(mandatory):
        groups.append(
            await _module_group(client, db, email=f"{tag}-author{i}@example.com", title=f"{tag} M{i}")
        )
    group = await _make_group(db, name=tag)
    await _as(client, db, f"{tag}-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        name=f"{tag} campaign",
        modules=[{"translation_group_id": g, "requirement": "mandatory"} for g in groups],
        targets=[{"type": "group", "id": str(group.id)}],
        **overrides,
    )
    return campaign, groups, group


async def _read_all_and_complete(client: AsyncClient, group_id: str) -> None:
    pages = (await client.get(f"/api/me/modules/{group_id}")).json()["pages"]
    for page in pages:
        assert (await client.post(f"/api/me/modules/{group_id}/pages/{page['id']}/view")).status_code == 200
    done = await client.post(f"/api/me/modules/{group_id}/complete")
    assert done.status_code == 200, done.text


async def _audit(db: AsyncSession, action: str) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


# --- Activation -----------------------------------------------------------------


async def test_activation_goes_draft_to_active_and_is_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _campaign(client, db_session, "act1")
    response = await client.post(f"{BASE}/{campaign['id']}/activate")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    entries = [e for e in await _audit(db_session, "campaign_activated") if e.detail["campaign_id"] == campaign["id"]]
    assert len(entries) == 1 and entries[0].detail["trigger"] == "manual"


async def test_activation_refused_with_an_unpublished_mandatory_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    draft_module = await _module_group(
        client, db_session, email="act2-author@example.com", title="Unfinished", publish=False
    )
    group = await _make_group(db_session, name="act2")
    await _as(client, db_session, "act2-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        modules=[{"translation_group_id": draft_module, "requirement": "mandatory"}],
        targets=[{"type": "group", "id": str(group.id)}],
    )
    response = await client.post(f"{BASE}/{campaign['id']}/activate")
    assert response.status_code == 422
    assert response.json()["detail"]["unpublished_modules"] == [draft_module]
    assert (await client.get(f"{BASE}/{campaign['id']}")).json()["status"] == "draft"


async def test_an_unpublished_recommended_module_does_not_block_activation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mandatory = await _module_group(client, db_session, email="act3-a@example.com", title="Req")
    optional = await _module_group(
        client, db_session, email="act3-b@example.com", title="Opt", publish=False
    )
    group = await _make_group(db_session, name="act3")
    await _as(client, db_session, "act3-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        modules=[
            {"translation_group_id": mandatory, "requirement": "mandatory"},
            {"translation_group_id": optional, "requirement": "recommended"},
        ],
        targets=[{"type": "group", "id": str(group.id)}],
    )
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200


async def test_activation_refused_without_a_target(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _module_group(client, db_session, email="act4-a@example.com", title="Req")
    await _as(client, db_session, "act4-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client, modules=[{"translation_group_id": module, "requirement": "mandatory"}]
    )
    response = await client.post(f"{BASE}/{campaign['id']}/activate")
    assert response.status_code == 422
    assert response.json()["detail"]["no_targets"] is True


async def test_invalid_transitions_are_conflicts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _campaign(client, db_session, "tr1")
    cid = campaign["id"]
    assert (await client.post(f"{BASE}/{cid}/close")).status_code == 409  # draft → closed
    assert (await client.post(f"{BASE}/{cid}/activate")).status_code == 200
    assert (await client.post(f"{BASE}/{cid}/activate")).status_code == 409  # already active
    assert (await client.post(f"{BASE}/{cid}/close")).status_code == 200
    assert (await client.post(f"{BASE}/{cid}/close")).status_code == 409
    assert (await client.post(f"{BASE}/{cid}/activate")).status_code == 409  # closed is terminal
    closed = await _audit(db_session, "campaign_closed")
    assert len([e for e in closed if e.detail["campaign_id"] == cid]) == 1


async def test_lifecycle_routes_hide_the_campaign_from_non_participants(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _campaign(client, db_session, "tr2")
    await _as(client, db_session, "tr2-other@example.com", "Content Manager")
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 404
    assert (await client.post(f"{BASE}/{campaign['id']}/close")).status_code == 404
    await _switch_to(client, db_session, email="tr2-learner@example.com")
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 403


async def test_a_collaborator_may_activate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _campaign(client, db_session, "tr3")
    await _make_user_with_role(db_session, email="tr3-collab@example.com", role_name="Content Manager")
    await client.post(f"{BASE}/{campaign['id']}/collaborators", json={"email": "tr3-collab@example.com"})
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="tr3-collab@example.com")
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200


# --- Email ----------------------------------------------------------------------


async def test_each_targeted_learner_is_emailed_once_in_their_language(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, _, group = await _campaign(client, db_session, "mail1")
    en = await _make_user_with_role(db_session, email="mail1-en@example.com", role_name="Learner")
    de = await _make_user_with_role(
        db_session, email="mail1-de@example.com", role_name="Learner", preferred_language="de"
    )
    for user in (en, de):
        await _add_to_group(db_session, user, group)
    await _as(client, db_session, "mail1-cm2@example.com", "Administrator")
    # An individual target who is also in the group must not be emailed twice.
    patched = await client.patch(
        f"{BASE}/{campaign['id']}",
        json={"targets": [
            {"type": "group", "id": str(group.id)},
            {"type": "user", "id": str(en.id)},
        ]},
    )
    assert patched.status_code == 200, patched.text
    sent_emails.clear()

    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200

    by_recipient: dict[str, list[dict[str, Any]]] = {}
    for mail in sent_emails:
        by_recipient.setdefault(mail["Destination"]["ToAddresses"][0], []).append(mail)
    assert sorted(by_recipient) == ["mail1-de@example.com", "mail1-en@example.com"]
    assert all(len(v) == 1 for v in by_recipient.values())
    assert "campaign" in by_recipient["mail1-en@example.com"][0]["Message"]["Subject"]["Data"]
    assert "kampagne" in by_recipient["mail1-de@example.com"][0]["Message"]["Subject"]["Data"].lower()


async def test_a_learner_joining_later_is_not_emailed_retroactively(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, _, group = await _campaign(client, db_session, "mail2")
    await client.post(f"{BASE}/{campaign['id']}/activate")
    sent_emails.clear()
    late = await _make_user_with_role(db_session, email="mail2-late@example.com", role_name="Learner")
    await _add_to_group(db_session, late, group)
    assert sent_emails == []


# --- Reach: the campaign branch of the one access decision --------------------


async def test_a_draft_campaign_reaches_nobody(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _campaign(client, db_session, "reach1")
    learner = await _make_user_with_role(db_session, email="reach1-l@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)
    await _login(client, email="reach1-l@example.com")
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 404
    assert (await client.get("/api/me/campaigns")).json() == []


async def test_late_joiner_sees_it_and_leaver_loses_it_but_keeps_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _campaign(client, db_session, "reach2")
    await client.post(f"{BASE}/{campaign['id']}/activate")
    learner = await _switch_to(client, db_session, email="reach2-l@example.com")
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 404

    await _add_to_group(db_session, learner, group)  # late joiner
    listed = (await client.get("/api/me/campaigns")).json()
    assert [c["id"] for c in listed] == [campaign["id"]]
    await _read_all_and_complete(client, groups[0])

    await _remove_from_group(db_session, learner, group)  # leaver
    assert (await client.get("/api/me/campaigns")).json() == []
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 404
    mine = (await client.get("/api/me/modules")).json()
    done = next(m for m in mine if m["translation_group_id"] == groups[0])
    assert done["completed_at"] is not None  # what they finished is theirs


async def test_assets_of_a_campaign_module_follow_the_same_decision(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import Module
    from app.routes.assets import authorize_asset_access

    campaign, groups, group = await _campaign(client, db_session, "reach3")
    learner = await _make_user_with_role(db_session, email="reach3-l@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)
    module = (
        await db_session.execute(
            select(Module).where(Module.translation_group_id == uuid.UUID(groups[0]))
        )
    ).scalar_one()

    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException):
        await authorize_asset_access(db_session, learner, module)  # draft campaign
    await client.post(f"{BASE}/{campaign['id']}/activate")
    await authorize_asset_access(db_session, learner, module)  # active: admitted
    await client.post(f"{BASE}/{campaign['id']}/close")
    with pytest.raises(HTTPException):
        await authorize_asset_access(db_session, learner, module)  # closed, nothing started


async def test_leaving_the_group_keeps_a_module_reachable_by_another_route(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Mixed routes: the campaign route is lost, the catalog route remains."""
    campaign, groups, group = await _campaign(client, db_session, "mixed1")
    await client.post(f"{BASE}/{campaign['id']}/activate")
    from app.models import Module

    module = (
        await db_session.execute(
            select(Module).where(Module.translation_group_id == uuid.UUID(groups[0]))
        )
    ).scalar_one()
    module.catalog_visible = True
    await db_session.commit()

    learner = await _switch_to(client, db_session, email="mixed1-l@example.com")
    await _add_to_group(db_session, learner, group)
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200
    await _remove_from_group(db_session, learner, group)
    assert (await client.get("/api/me/campaigns")).json() == []
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200  # via catalog


# --- Progress and live completion --------------------------------------------------


async def test_progress_counts_required_modules_and_flags_requirement(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mandatory = [
        await _module_group(client, db_session, email=f"prog1-a{i}@example.com", title=f"Req {i}")
        for i in range(2)
    ]
    optional = await _module_group(client, db_session, email="prog1-o@example.com", title="Opt")
    group = await _make_group(db_session, name="prog1")
    await _as(client, db_session, "prog1-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        name="Prog",
        due_date="2099-01-01",
        modules=[
            {"translation_group_id": mandatory[0], "requirement": "mandatory"},
            {"translation_group_id": optional, "requirement": "recommended"},
            {"translation_group_id": mandatory[1], "requirement": "mandatory"},
        ],
        targets=[{"type": "group", "id": str(group.id)}],
    )
    await client.post(f"{BASE}/{campaign['id']}/activate")
    learner = await _switch_to(client, db_session, email="prog1-l@example.com")
    await _add_to_group(db_session, learner, group)

    first = (await client.get("/api/me/campaigns")).json()[0]
    assert (first["required_done"], first["required_total"], first["complete"]) == (0, 2, False)
    assert [m["requirement"] for m in first["modules"]] == ["mandatory", "recommended", "mandatory"]
    assert first["due_date"] == "2099-01-01" and first["overdue"] is False

    await _read_all_and_complete(client, optional)  # recommended does not count
    await _read_all_and_complete(client, mandatory[0])
    mid = (await client.get("/api/me/campaigns")).json()[0]
    assert (mid["required_done"], mid["complete"]) == (1, False)
    assert [m["state"] for m in mid["modules"]] == ["completed", "completed", "not_started"]

    await _read_all_and_complete(client, mandatory[1])
    assert (await client.get("/api/me/campaigns")).json()[0]["complete"] is True


async def test_a_substantive_republish_reopens_a_complete_campaign(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _campaign(client, db_session, "reopen1")
    await client.post(f"{BASE}/{campaign['id']}/activate")
    learner = await _switch_to(client, db_session, email="reopen1-l@example.com")
    await _add_to_group(db_session, learner, group)
    await _read_all_and_complete(client, groups[0])
    assert (await client.get("/api/me/campaigns")).json()[0]["complete"] is True

    from app.models import Module

    module = (
        await db_session.execute(
            select(Module).where(Module.translation_group_id == uuid.UUID(groups[0]))
        )
    ).scalar_one()
    await _login(client, email="reopen1-author0@example.com")
    published = await client.post(
        f"/api/content/modules/{module.id}/publish", json={"revision_kind": "substantive"}
    )
    assert published.status_code == 200, published.text

    await _login(client, email="reopen1-l@example.com")
    reopened = (await client.get("/api/me/campaigns")).json()[0]
    assert reopened["complete"] is False and reopened["required_done"] == 0
    assert reopened["modules"][0]["state"] == "in_progress"


async def test_overdue_is_flagged_on_an_active_campaign_until_it_is_complete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _campaign(client, db_session, "od1", due_date="2020-01-01")
    await client.post(f"{BASE}/{campaign['id']}/activate")
    learner = await _switch_to(client, db_session, email="od1-l@example.com")
    await _add_to_group(db_session, learner, group)
    row = (await client.get("/api/me/campaigns")).json()[0]
    assert row["overdue"] is True and row["modules"][0]["overdue"] is True
    await _read_all_and_complete(client, groups[0])
    row = (await client.get("/api/me/campaigns")).json()[0]
    assert row["overdue"] is False and row["complete"] is True


# --- Closing --------------------------------------------------------------------


async def test_closing_blocks_new_starts_but_keeps_progress_readable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _campaign(client, db_session, "close1", mandatory=2)
    await client.post(f"{BASE}/{campaign['id']}/activate")
    learner = await _switch_to(client, db_session, email="close1-l@example.com")
    await _add_to_group(db_session, learner, group)
    await _read_all_and_complete(client, groups[0])  # started and finished before close

    await _login(client, email="close1-cm@example.com")
    assert (await client.post(f"{BASE}/{campaign['id']}/close")).status_code == 200

    await _login(client, email="close1-l@example.com")
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200  # record readable
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 404  # no new starts
    listed = (await client.get("/api/me/campaigns")).json()[0]
    assert listed["status"] == "closed" and listed["required_done"] == 1
    assert listed["overdue"] is False
    assert [m["available"] for m in listed["modules"]] == [True, False]


async def test_a_closed_campaign_nobody_started_is_not_listed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, group = await _campaign(client, db_session, "close2")
    await client.post(f"{BASE}/{campaign['id']}/activate")
    await client.post(f"{BASE}/{campaign['id']}/close")
    learner = await _switch_to(client, db_session, email="close2-l@example.com")
    await _add_to_group(db_session, learner, group)
    assert (await client.get("/api/me/campaigns")).json() == []


# --- The daily job ---------------------------------------------------------------


async def test_the_daily_job_activates_by_start_date_exactly_once(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    # Asserts on this campaign only: the job sweeps every due draft in the
    # database, so a count of "campaigns activated" would depend on whatever
    # else is lying around.
    campaign, _, group = await _campaign(
        client, db_session, "job1", start_date="2026-11-01"
    )
    learner = await _make_user_with_role(db_session, email="job1-l@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)
    ses = FakeSESClient(sent_emails)

    def mails_to_learner() -> int:
        return sum(1 for m in sent_emails if m["Destination"]["ToAddresses"] == ["job1-l@example.com"])

    async def status() -> str:
        return (await client.get(f"{BASE}/{campaign['id']}")).json()["status"]

    await activate_due_campaigns(db_session, ses, today=date(2026, 10, 31))
    assert await status() == "draft" and mails_to_learner() == 0

    await activate_due_campaigns(db_session, ses, today=date(2026, 11, 1))
    assert await status() == "active" and mails_to_learner() == 1

    await activate_due_campaigns(db_session, ses, today=date(2026, 11, 1))
    assert mails_to_learner() == 1  # the rerun did nothing twice
    entry = [
        e
        for e in await _audit(db_session, "campaign_activated")
        if e.detail["campaign_id"] == campaign["id"]
    ]
    assert len(entry) == 1 and entry[0].detail["trigger"] == "start_date"


async def test_the_daily_job_leaves_an_unready_campaign_in_draft(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    module = await _module_group(
        client, db_session, email="job2-a@example.com", title="Unfinished", publish=False
    )
    group = await _make_group(db_session, name="job2")
    await _as(client, db_session, "job2-cm@example.com", "Content Manager")
    campaign = await _new_campaign(
        client,
        start_date="2020-01-01",
        modules=[{"translation_group_id": module, "requirement": "mandatory"}],
        targets=[{"type": "group", "id": str(group.id)}],
    )
    await activate_due_campaigns(db_session, FakeSESClient(sent_emails))
    assert (await client.get(f"{BASE}/{campaign['id']}")).json()["status"] == "draft"

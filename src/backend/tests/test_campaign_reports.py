"""Campaign reports (Release 2, ticket 12).

What this file holds down: the Release 1 privacy split carried over to
campaigns — a Content Manager sees per-group counts and never a name or email,
an Administrator sees the per-learner roster and alone may export it; counts use
the same live completion notion as the learner's view (a superseded completion
is outstanding but keeps its record); a suspended campaign counts as suspended
with `overdue` frozen; and only people who may edit a campaign may read its
report.
"""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModuleProgress
from tests.test_assignments import _login, _make_user_with_role
from tests.test_campaign_reminders import _live_campaign, _module_of
from tests.test_campaigns import _as
from tests.test_reminders import _complete

BASE = "/api/content/campaigns"


async def _relogin(client: AsyncClient, email: str) -> None:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=email)


async def _report(client: AsyncClient, campaign_id: str) -> dict[str, Any]:
    response = await client.get(f"{BASE}/{campaign_id}/report")
    assert response.status_code == 200, response.text
    return response.json()


async def _finish(db: AsyncSession, user: Any, groups: list[str]) -> None:
    for group_id in groups:
        module = await _module_of(db, group_id)
        await _complete(
            db,
            user_id=user.id,
            translation_group_id=module.translation_group_id,
            module_id=module.id,
        )


async def _start(db: AsyncSession, user: Any, group_id: str) -> ModuleProgress:
    module = await _module_of(db, group_id)
    row = ModuleProgress(
        user_id=user.id,
        translation_group_id=module.translation_group_id,
        module_id=module.id,
        pages_viewed=[],
    )
    db.add(row)
    await db.commit()
    return row


# --- Content Manager: aggregates only ---------------------------------------------


async def test_content_manager_gets_group_counts_and_average_progress_without_names(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(
        client, db_session, "rp1", due_in=5, learners=3, mandatory=2
    )
    await _finish(db_session, users[0], groups)  # complete: 2 of 2
    await _finish(db_session, users[1], groups[:1])  # in progress: 1 of 2
    # users[2] has not started.

    report = await _report(client, campaign["id"])

    assert "learners" not in report
    (group,) = report["groups"]
    assert group["member_count"] == 3
    assert (group["completed"], group["in_progress"], group["not_started"]) == (1, 1, 1)
    assert (group["overdue"], group["suspended"]) == (0, 0)
    assert group["average_progress"] == 50  # (100 + 50 + 0) / 3
    body = str([report])
    for user in users:
        assert user.email not in body
    assert [m["requirement"] for m in report["modules"]] == ["mandatory", "mandatory"]


async def test_touching_a_module_moves_a_learner_from_not_started_to_in_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(client, db_session, "rp2", due_in=5)
    assert (await _report(client, campaign["id"]))["groups"][0]["not_started"] == 1
    await _start(db_session, users[0], groups[0])
    group = (await _report(client, campaign["id"]))["groups"][0]
    assert (group["in_progress"], group["not_started"]) == (1, 0)


async def test_overdue_counts_unfinished_learners_once_the_due_date_has_passed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(
        client, db_session, "rp3", due_in=-1, learners=2
    )
    await _finish(db_session, users[0], groups)

    group = (await _report(client, campaign["id"]))["groups"][0]
    assert group["completed"] == 1
    assert group["overdue"] == 1  # the finisher is never overdue


async def test_a_suspended_campaign_counts_suspended_and_freezes_overdue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(
        client, db_session, "rp4", due_in=-1, learners=3
    )
    await _finish(db_session, users[0], groups)
    await _start(db_session, users[1], groups[0])
    assert (await client.post(f"{BASE}/{campaign['id']}/suspend")).status_code == 200

    group = (await _report(client, campaign["id"]))["groups"][0]
    assert group["completed"] == 1
    assert group["suspended"] == 2
    assert (group["in_progress"], group["not_started"], group["overdue"]) == (0, 0, 0)
    assert (
        group["completed"] + group["in_progress"] + group["not_started"] + group["suspended"]
        == group["member_count"]
    )


async def test_individual_targets_never_appear_in_the_group_aggregate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, users = await _live_campaign(client, db_session, "rp5", due_in=5)
    outsider = await _make_user_with_role(
        db_session, email="rp5-solo@example.com", role_name="Learner"
    )
    await _as(client, db_session, "rp5-admin@example.com", "Administrator")
    patched = await client.patch(
        f"{BASE}/{campaign['id']}",
        json={
            "targets": [
                *({"type": t["type"], "id": t["id"]} for t in campaign["targets"]),
                {"type": "user", "id": str(outsider.id)},
            ]
        },
    )
    assert patched.status_code == 200, patched.text

    admin_report = await _report(client, campaign["id"])
    assert {row["email"] for row in admin_report["learners"]} == {
        users[0].email,
        "rp5-solo@example.com",
    }

    await _relogin(client, "rp5-cm@example.com")
    (group,) = (await _report(client, campaign["id"]))["groups"]
    assert group["member_count"] == 1


# --- Administrator: the roster ----------------------------------------------------


async def test_administrator_gets_the_roster_with_each_modules_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(
        client, db_session, "rp6", due_in=5, learners=2, mandatory=2
    )
    await _finish(db_session, users[0], groups[:1])
    await _as(client, db_session, "rp6-admin@example.com", "Administrator")

    report = await _report(client, campaign["id"])

    assert "groups" not in report
    by_email = {row["email"]: row for row in report["learners"]}
    first = by_email[users[0].email]
    assert first["state"] == "in_progress"
    assert (first["required_done"], first["required_total"], first["progress_percent"]) == (1, 2, 50)
    assert [c["state"] for c in first["modules"]] == ["completed", "not_started"]
    assert first["modules"][0]["completed_version_number"] == 1
    assert by_email[users[1].email]["state"] == "not_started"
    assert by_email[users[0].email]["name"]


async def test_a_superseded_completion_reports_outstanding_but_keeps_its_record(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(client, db_session, "rp7", due_in=5)
    await _finish(db_session, users[0], groups)
    module = await _module_of(db_session, groups[0])
    row = (
        await db_session.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == users[0].id,
                ModuleProgress.translation_group_id == module.translation_group_id,
            )
        )
    ).scalar_one()
    row.superseded_at = datetime.now(UTC)
    await db_session.commit()

    group = (await _report(client, campaign["id"]))["groups"][0]
    assert (group["completed"], group["in_progress"]) == (0, 1)

    await _as(client, db_session, "rp7-admin@example.com", "Administrator")
    (learner,) = (await _report(client, campaign["id"]))["learners"]
    assert learner["state"] == "in_progress"
    assert learner["modules"][0]["state"] == "in_progress"
    assert learner["modules"][0]["completed_at"] is not None
    assert learner["modules"][0]["completed_version_number"] == 1


async def test_a_deleted_module_is_marked_unavailable_and_not_required(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(
        client, db_session, "rp8", due_in=5, mandatory=2
    )
    await _finish(db_session, users[0], groups[:1])
    deleted = await _module_of(db_session, groups[1])
    deleted.status = "deleted"
    await db_session.commit()
    await _as(client, db_session, "rp8-admin@example.com", "Administrator")

    report = await _report(client, campaign["id"])

    assert [m["unavailable"] for m in report["modules"]] == [False, True]
    (learner,) = report["learners"]
    assert learner["state"] == "completed"
    assert learner["required_total"] == 1


# --- Who may read it ----------------------------------------------------------------


async def test_non_participants_get_a_404_and_collaborators_a_report(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, _, _ = await _live_campaign(client, db_session, "rp9", due_in=5)
    collaborator = await _make_user_with_role(
        db_session, email="rp9-collab@example.com", role_name="Content Manager"
    )
    added = await client.post(
        f"{BASE}/{campaign['id']}/collaborators", json={"email": collaborator.email}
    )
    assert added.status_code in (200, 201), added.text

    await _relogin(client, "rp9-collab@example.com")
    assert (await client.get(f"{BASE}/{campaign['id']}/report")).status_code == 200

    await _as(client, db_session, "rp9-stranger@example.com", "Content Manager")
    assert (await client.get(f"{BASE}/{campaign['id']}/report")).status_code == 404
    assert (await client.get(f"{BASE}/{campaign['id']}/report.csv")).status_code == 403

    await _as(client, db_session, "rp9-learner@example.com", "Learner")
    assert (await client.get(f"{BASE}/{campaign['id']}/report")).status_code == 403


async def test_unknown_campaign_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    await _as(client, db_session, "rp10-admin@example.com", "Administrator")
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"{BASE}/{missing}/report")).status_code == 404
    assert (await client.get(f"{BASE}/{missing}/report.csv")).status_code == 404


# --- CSV ----------------------------------------------------------------------------


async def test_csv_is_administrator_only_and_lists_every_learner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, users = await _live_campaign(
        client, db_session, "rp11", due_in=5, learners=2, mandatory=2
    )
    await _finish(db_session, users[0], groups)
    assert (await client.get(f"{BASE}/{campaign['id']}/report.csv")).status_code == 403

    await _as(client, db_session, "rp11-admin@example.com", "Administrator")
    response = await client.get(f"{BASE}/{campaign['id']}/report.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = [line.split(",") for line in response.text.strip().splitlines()]
    assert rows[0][:7] == [
        "Name", "Email", "Status", "Overdue", "Required Done", "Required Total", "Progress %",
    ]
    assert len(rows[0]) == 9  # two module columns
    by_email = {row[1]: row for row in rows[1:]}
    assert by_email[users[0].email][2] == "completed"
    assert by_email[users[0].email][7:] == ["completed", "completed"]
    assert by_email[users[1].email][2] == "not_started"

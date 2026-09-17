"""Reporting: did people do the training?

Two shapes behind one URL (`GET /api/content/modules/{id}/report`), chosen by
the caller's role on the server — a Content Manager gets per-group counts and
never a name or email; an Administrator gets the full roster, and only an
Administrator may export it as CSV. `app.reporting` walks the same assignment
resolution `app.assignments` and `app.reminders` already rely on (live group
membership, never expanded and stored), so these tests lean on the same
fixtures `tests.test_assignments` built for that.
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.security.system_settings import set_reminder_timezone
from tests.test_assignments import (
    _add_to_group,
    _doc,
    _login,
    _login_with_role,
    _make_group,
    _make_user_with_role,
)

YESTERDAY = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


async def _pin_timezone_to_utc(db_session: AsyncSession) -> None:
    # So "overdue" in these tests means exactly `datetime.now(UTC).date()`,
    # independent of what the real `Europe/Berlin` default would say right now
    # — the same convention `tests/test_reminders.py` uses.
    await set_reminder_timezone(db_session, "UTC")
    await db_session.commit()


async def _create_two_page_module(
    client: AsyncClient, db_session: AsyncSession, *, author_email: str
) -> dict[str, Any]:
    await _login_with_role(client, db_session, email=author_email, role_name="Content Manager")
    created = await client.post(
        "/api/content/modules", json={"title": "Fire Safety", "language": "en"}
    )
    assert created.status_code == 201
    module = created.json()

    revision = 1
    for index in range(2):
        page = await client.post(
            f"/api/content/modules/{module['id']}/pages",
            json={
                "draft_revision": revision,
                "title": f"Page {index + 1}",
                "schema_version": SCHEMA_VERSION,
                "body": _doc(f"Text {index + 1}"),
            },
        )
        assert page.status_code == 201, page.text
        revision += 1

    published = await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
    )
    assert published.status_code == 200, published.text
    return published.json()


async def _view_one_page(client: AsyncClient, *, translation_group_id: str, email: str) -> None:
    await _login(client, email=email)
    pages = (await client.get(f"/api/me/modules/{translation_group_id}")).json()["pages"]
    viewed = await client.post(
        f"/api/me/modules/{translation_group_id}/pages/{pages[0]['id']}/view"
    )
    assert viewed.status_code == 200


async def _complete_every_page(client: AsyncClient, *, translation_group_id: str, email: str) -> None:
    await _login(client, email=email)
    pages = (await client.get(f"/api/me/modules/{translation_group_id}")).json()["pages"]
    for page in pages:
        await client.post(f"/api/me/modules/{translation_group_id}/pages/{page['id']}/view")
    completed = await client.post(f"/api/me/modules/{translation_group_id}/complete")
    assert completed.status_code == 200


async def _assign_to_group(
    client: AsyncClient, *, module_id: str, group_id: str, due_date: str | None = None
) -> None:
    response = await client.post(
        f"/api/content/modules/{module_id}/assignments",
        json={
            "target_type": "group",
            "target_id": group_id,
            "requirement": "mandatory",
            "due_date": due_date,
        },
    )
    assert response.status_code == 201, response.text


async def _setup_three_learner_group(
    client: AsyncClient, db_session: AsyncSession, *, prefix: str
) -> dict[str, Any]:
    """One module assigned to a group of three: one completed, one part-way
    through, one who never opened it — the mix every count in the report has
    to get right at once."""
    module = await _create_two_page_module(client, db_session, author_email=f"{prefix}-author@example.com")
    group = await _make_group(db_session, name=f"{prefix} group")

    completed_learner = await _make_user_with_role(
        db_session, email=f"{prefix}-completed@example.com", role_name="Learner"
    )
    in_progress_learner = await _make_user_with_role(
        db_session, email=f"{prefix}-inprogress@example.com", role_name="Learner"
    )
    not_started_learner = await _make_user_with_role(
        db_session, email=f"{prefix}-notstarted@example.com", role_name="Learner"
    )
    for learner in (completed_learner, in_progress_learner, not_started_learner):
        await _add_to_group(db_session, learner, group)

    await _login_with_role(client, db_session, email=f"{prefix}-cm@example.com", role_name="Content Manager")
    await _assign_to_group(client, module_id=module["id"], group_id=str(group.id), due_date=YESTERDAY)

    await _complete_every_page(
        client, translation_group_id=module["translation_group_id"], email=completed_learner.email
    )
    await _view_one_page(
        client, translation_group_id=module["translation_group_id"], email=in_progress_learner.email
    )

    return {
        "module": module,
        "group": group,
        "completed_learner": completed_learner,
        "in_progress_learner": in_progress_learner,
        "not_started_learner": not_started_learner,
    }


# --- Content Manager: aggregate counts, no identities -----------------------


async def test_a_content_manager_sees_per_group_counts_and_no_identities(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _pin_timezone_to_utc(db_session)
    fixture = await _setup_three_learner_group(client, db_session, prefix="cmcounts")

    await _login_with_role(client, db_session, email="cmcounts-viewer@example.com", role_name="Content Manager")
    response = await client.get(f"/api/content/modules/{fixture['module']['id']}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["translation_group_id"] == fixture["module"]["translation_group_id"]
    assert len(body["groups"]) == 1
    group_row = body["groups"][0]
    assert group_row["group_id"] == str(fixture["group"].id)
    assert group_row["member_count"] == 3
    assert group_row["completed"] == 1
    assert group_row["in_progress"] == 1
    assert group_row["not_started"] == 1
    # Both non-completed learners are past yesterday's due date.
    assert group_row["overdue"] == 2

    raw = response.text
    for learner in (fixture["completed_learner"], fixture["in_progress_learner"], fixture["not_started_learner"]):
        assert learner.email not in raw
        assert str(learner.id) not in raw
    assert "user_id" not in raw
    assert "email" not in raw


async def test_a_content_manager_gets_403_on_the_csv_export(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    fixture = await _setup_three_learner_group(client, db_session, prefix="cmcsv")
    await _login_with_role(client, db_session, email="cmcsv-viewer@example.com", role_name="Content Manager")

    response = await client.get(f"/api/content/modules/{fixture['module']['id']}/report.csv")

    assert response.status_code == 403


async def test_counts_include_a_learner_who_joins_the_group_after_assignment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_two_page_module(client, db_session, author_email="latejoin-author@example.com")
    group = await _make_group(db_session, name="Late Joiners")

    await _login_with_role(client, db_session, email="latejoin-cm@example.com", role_name="Content Manager")
    await _assign_to_group(client, module_id=module["id"], group_id=str(group.id))

    latecomer = await _make_user_with_role(
        db_session, email="latejoin-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, latecomer, group)

    await _login_with_role(client, db_session, email="latejoin-viewer@example.com", role_name="Content Manager")
    response = await client.get(f"/api/content/modules/{module['id']}/report")

    group_row = response.json()["groups"][0]
    assert group_row["member_count"] == 1
    assert group_row["not_started"] == 1


# --- Administrator: the full roster ------------------------------------------


async def test_an_administrator_sees_the_full_roster_with_identities_and_versions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _pin_timezone_to_utc(db_session)
    fixture = await _setup_three_learner_group(client, db_session, prefix="adminroster")

    await _login_with_role(client, db_session, email="adminroster-viewer@example.com", role_name="Administrator")
    response = await client.get(f"/api/content/modules/{fixture['module']['id']}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["translation_group_id"] == fixture["module"]["translation_group_id"]
    learners = {row["user_id"]: row for row in body["learners"]}

    completed_row = learners[str(fixture["completed_learner"].id)]
    assert completed_row["email"] == fixture["completed_learner"].email
    assert completed_row["state"] == "completed"
    assert completed_row["completed_version_number"] == 1
    assert completed_row["completed_at"] is not None
    assert completed_row["overdue"] is False

    in_progress_row = learners[str(fixture["in_progress_learner"].id)]
    assert in_progress_row["state"] == "in_progress"
    assert in_progress_row["overdue"] is True

    not_started_row = learners[str(fixture["not_started_learner"].id)]
    assert not_started_row["state"] == "not_started"
    assert not_started_row["overdue"] is True


async def test_report_deduplicates_a_learner_targeted_both_directly_and_via_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_two_page_module(client, db_session, author_email="dedupe-author@example.com")
    group = await _make_group(db_session, name="Dedupe Group")
    learner = await _make_user_with_role(db_session, email="dedupe-learner@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)

    await _login_with_role(client, db_session, email="dedupe-admin@example.com", role_name="Administrator")
    await _assign_to_group(client, module_id=module["id"], group_id=str(group.id), due_date="2027-06-01")
    individual = await client.post(
        f"/api/content/modules/{module['id']}/assignments",
        json={
            "target_type": "user",
            "target_id": str(learner.id),
            "requirement": "mandatory",
            "due_date": "2027-01-01",
        },
    )
    assert individual.status_code == 201, individual.text

    response = await client.get(f"/api/content/modules/{module['id']}/report")

    rows = [row for row in response.json()["learners"] if row["user_id"] == str(learner.id)]
    assert len(rows) == 1
    assert rows[0]["due_date"] == "2027-01-01"


async def test_a_superseded_completion_is_reported_as_outstanding_but_keeps_its_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_two_page_module(client, db_session, author_email="superseded-author@example.com")
    group = await _make_group(db_session, name="Superseded Group")
    learner = await _make_user_with_role(db_session, email="superseded-learner@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)

    await _login_with_role(client, db_session, email="superseded-cm@example.com", role_name="Content Manager")
    await _assign_to_group(client, module_id=module["id"], group_id=str(group.id))

    await _complete_every_page(
        client, translation_group_id=module["translation_group_id"], email=learner.email
    )

    await _login(client, email="superseded-cm@example.com")
    republished = await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "substantive"}
    )
    assert republished.status_code == 200, republished.text

    await _login_with_role(client, db_session, email="superseded-admin@example.com", role_name="Administrator")
    response = await client.get(f"/api/content/modules/{module['id']}/report")

    row = next(
        row for row in response.json()["learners"] if row["user_id"] == str(learner.id)
    )
    assert row["state"] == "in_progress"
    assert row["completed_at"] is not None
    assert row["completed_version_number"] == 1


# --- CSV export ---------------------------------------------------------------


async def test_counts_aggregate_across_every_language_variant_of_the_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A translation group is one body of material however many languages it is
    written in — the report has to count a German reader and an English reader
    of the same group as the same population, not two."""
    await _login_with_role(client, db_session, email="i18n-cm@example.com", role_name="Content Manager")
    en_created = await client.post(
        "/api/content/modules", json={"title": "Fire Safety", "language": "en"}
    )
    en_module = en_created.json()
    de_created = await client.post(
        "/api/content/modules", json={"title": "Brandschutz", "language": "de"}
    )
    de_module = de_created.json()

    for module in (en_module, de_module):
        page = await client.post(
            f"/api/content/modules/{module['id']}/pages",
            json={
                "draft_revision": 1,
                "title": "Page 1",
                "schema_version": SCHEMA_VERSION,
                "body": _doc("Text."),
            },
        )
        assert page.status_code == 201, page.text
        published = await client.post(
            f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
        )
        assert published.status_code == 200, published.text

    linked = await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )
    assert linked.status_code == 201, linked.text
    translation_group_id = en_module["translation_group_id"]

    group = await _make_group(db_session, name="i18n workforce")
    english_learner = await _make_user_with_role(
        db_session, email="i18n-en-learner@example.com", role_name="Learner", preferred_language="en"
    )
    german_learner = await _make_user_with_role(
        db_session, email="i18n-de-learner@example.com", role_name="Learner", preferred_language="de"
    )
    for learner in (english_learner, german_learner):
        await _add_to_group(db_session, learner, group)

    await _login_with_role(client, db_session, email="i18n-assign@example.com", role_name="Content Manager")
    await _assign_to_group(client, module_id=en_module["id"], group_id=str(group.id))

    # Each learner is resolved to their own preferred language, but both read
    # the same translation group's material.
    await _complete_every_page(client, translation_group_id=translation_group_id, email=english_learner.email)
    await _complete_every_page(client, translation_group_id=translation_group_id, email=german_learner.email)

    await _login_with_role(client, db_session, email="i18n-viewer@example.com", role_name="Content Manager")
    response = await client.get(f"/api/content/modules/{en_module['id']}/report")

    group_row = response.json()["groups"][0]
    assert group_row["member_count"] == 2
    assert group_row["completed"] == 2


async def test_the_csv_export_lists_the_roster_and_is_administrator_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _pin_timezone_to_utc(db_session)
    fixture = await _setup_three_learner_group(client, db_session, prefix="csv")

    await _login_with_role(client, db_session, email="csv-admin@example.com", role_name="Administrator")
    response = await client.get(f"/api/content/modules/{fixture['module']['id']}/report.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(response.text)))
    header, *data_rows = rows
    assert header == [
        "Name",
        "Email",
        "Status",
        "Completed At",
        "Completed Version",
        "Due Date",
        "Overdue",
    ]
    emails = {row[1] for row in data_rows}
    assert emails == {
        fixture["completed_learner"].email,
        fixture["in_progress_learner"].email,
        fixture["not_started_learner"].email,
    }
    completed_row = next(row for row in data_rows if row[1] == fixture["completed_learner"].email)
    assert completed_row[2] == "completed"
    assert completed_row[4] == "1"

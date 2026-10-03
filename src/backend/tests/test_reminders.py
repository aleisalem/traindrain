"""Reminders: the scheduled cadence, the manual nudge, and the one hard rule
both paths share — at most one email per learner per module per day.

`app.reminders.run_scheduled_reminders` and `send_manual_reminders` are
exercised directly against `db_session`, the same in-transaction session the
`client` fixture's routes use, rather than only through HTTP: the scheduled
path has no route of its own — it is what `app.jobs.send_reminders` calls —
so a direct call is the honest way to test it, and calling the manual path
the same way keeps the two tests directly comparable.

The reminder timezone is pinned to UTC in every test (`set_reminder_timezone`)
so "today" in these tests is exactly `datetime.now(UTC).date()`, independent
of whatever `Europe/Berlin` (the real default) would say at the moment the
suite happens to run.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModuleProgress
from app.reminders import run_scheduled_reminders, send_manual_reminders
from app.security.system_settings import set_reminder_timezone
from tests.conftest import FakeSESClient
from tests.test_assignments import (
    _add_to_group,
    _create_module,
    _login_with_role,
    _make_group,
    _make_user_with_role,
)


async def _today(db_session: AsyncSession) -> date:
    await set_reminder_timezone(db_session, "UTC")
    await db_session.commit()
    return datetime.now(UTC).date()


async def _assign(
    client: AsyncClient,
    *,
    module_id: str,
    target_type: str,
    target_id: uuid.UUID,
    due_date: date,
    requirement: str = "mandatory",
    auto_reminders: bool = True,
) -> None:
    response = await client.post(
        f"/api/content/modules/{module_id}/assignments",
        json={
            "target_type": target_type,
            "target_id": str(target_id),
            "requirement": requirement,
            "auto_reminders": auto_reminders,
            "due_date": due_date.isoformat(),
        },
    )
    assert response.status_code == 201, response.text


def _reminder_emails_to(sent_emails: list[dict[str, Any]]) -> list[str]:
    return [
        email["Destination"]["ToAddresses"][0]
        for email in sent_emails
        if "reminder" in email["Message"]["Subject"]["Data"].lower()
        or "erinnerung" in email["Message"]["Subject"]["Data"].lower()
    ]


async def _complete(
    db_session: AsyncSession, *, user_id: uuid.UUID, translation_group_id: uuid.UUID, module_id: uuid.UUID
) -> None:
    db_session.add(
        ModuleProgress(
            user_id=user_id,
            translation_group_id=translation_group_id,
            module_id=module_id,
            pages_viewed=[],
            completed_at=datetime.now(UTC),
            completed_version_number=1,
            completed_module_id=module_id,
        )
    )
    await db_session.commit()


# --- Cadence boundaries ------------------------------------------------------


async def test_reminder_fires_seven_days_before_due(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="rem7-author@example.com")
    group = await _make_group(db_session, name="Rem7 Group")
    learner = await _make_user_with_role(
        db_session, email="rem7-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="rem7-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today + timedelta(days=7),
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 1
    assert "rem7-learner@example.com" in _reminder_emails_to(sent_emails)


async def test_reminder_fires_one_day_before_due(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="rem1-author@example.com")
    group = await _make_group(db_session, name="Rem1 Group")
    learner = await _make_user_with_role(
        db_session, email="rem1-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="rem1-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today + timedelta(days=1),
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 1
    assert "rem1-learner@example.com" in _reminder_emails_to(sent_emails)


async def test_reminder_fires_on_the_due_date(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remdue-author@example.com")
    group = await _make_group(db_session, name="RemDue Group")
    learner = await _make_user_with_role(
        db_session, email="remdue-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remdue-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 1
    assert "remdue-learner@example.com" in _reminder_emails_to(sent_emails)


async def test_reminder_fires_weekly_while_overdue(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remover-author@example.com")
    group = await _make_group(db_session, name="RemOver Group")
    learner = await _make_user_with_role(
        db_session, email="remover-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remover-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today - timedelta(days=14),
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 1
    assert "remover-learner@example.com" in _reminder_emails_to(sent_emails)


async def test_no_reminder_off_the_cadence(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    """Three days before due, or three days overdue, are not checkpoints."""
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remoff-author@example.com")
    group = await _make_group(db_session, name="RemOff Group")
    learner = await _make_user_with_role(
        db_session, email="remoff-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remoff-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today + timedelta(days=3),
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 0
    assert _reminder_emails_to(sent_emails) == []


# --- Who never gets reminded automatically ----------------------------------


async def test_a_recommended_assignment_is_never_reminded(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remrec-author@example.com")
    group = await _make_group(db_session, name="RemRec Group")
    learner = await _make_user_with_role(
        db_session, email="remrec-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remrec-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today, requirement="recommended",
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 0
    assert _reminder_emails_to(sent_emails) == []


async def test_an_assignment_with_reminders_off_is_never_reminded(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remoffauto-author@example.com")
    group = await _make_group(db_session, name="RemOffAuto Group")
    learner = await _make_user_with_role(
        db_session, email="remoffauto-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(
        client, db_session, email="remoffauto-cm@example.com", role_name="Content Manager"
    )
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today, auto_reminders=False,
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 0
    assert _reminder_emails_to(sent_emails) == []


async def test_a_learner_who_already_completed_is_not_reminded(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remdone-author@example.com")
    group = await _make_group(db_session, name="RemDone Group")
    learner = await _make_user_with_role(
        db_session, email="remdone-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remdone-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )
    await _complete(
        db_session,
        user_id=learner.id,
        translation_group_id=uuid.UUID(module["translation_group_id"]),
        module_id=uuid.UUID(module["id"]),
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 0


# --- Idempotency and the daily cap ------------------------------------------


async def test_running_the_job_twice_in_a_day_sends_nothing_the_second_time(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remidem-author@example.com")
    group = await _make_group(db_session, name="RemIdem Group")
    learner = await _make_user_with_role(
        db_session, email="remidem-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remidem-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )

    ses = FakeSESClient(sent_emails)
    first = await run_scheduled_reminders(db_session, ses)
    await db_session.commit()
    second = await run_scheduled_reminders(db_session, ses)
    await db_session.commit()

    assert first == 1
    assert second == 0


async def test_the_daily_cap_holds_across_both_the_scheduled_and_manual_path(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remcap-author@example.com")
    group = await _make_group(db_session, name="RemCap Group")
    learner = await _make_user_with_role(
        db_session, email="remcap-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remcap-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )

    ses = FakeSESClient(sent_emails)
    scheduled_count = await run_scheduled_reminders(db_session, ses)
    await db_session.commit()
    manual_count = await send_manual_reminders(
        db_session, ses, translation_group_id=uuid.UUID(module["translation_group_id"])
    )
    await db_session.commit()

    assert scheduled_count == 1
    # The learner the scheduled run already reached today is skipped by the
    # manual path, not emailed a second time.
    assert manual_count == 0


async def test_a_learner_targeted_twice_is_only_reminded_once_a_day(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    """A group assignment and an individual assignment covering the same
    learner, for the same material, must still only reach them once."""
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remtwice-author@example.com")
    group = await _make_group(db_session, name="RemTwice Group")
    learner = await _make_user_with_role(
        db_session, email="remtwice-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(
        client, db_session, email="remtwice-admin@example.com", role_name="Administrator"
    )
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )
    await _assign(
        client, module_id=module["id"], target_type="user", target_id=learner.id, due_date=today
    )

    sent_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert sent_count == 1


# --- The manual nudge endpoint -----------------------------------------------


async def test_a_content_manager_cannot_trigger_the_manual_nudge(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _create_module(client, db_session, author_email="remnudge403-author@example.com")
    await _login_with_role(
        client, db_session, email="remnudge403-cm@example.com", role_name="Content Manager"
    )

    response = await client.post(f"/api/content/modules/{module['id']}/remind")

    assert response.status_code == 403


async def test_an_administrator_can_nudge_everyone_outstanding(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remnudge-author@example.com")
    group = await _make_group(db_session, name="RemNudge Group")
    learner = await _make_user_with_role(
        db_session, email="remnudge-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(
        client, db_session, email="remnudge-cm@example.com", role_name="Content Manager"
    )
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id,
        due_date=today + timedelta(days=30),
    )
    await _switch_to_admin(client, db_session, email="remnudge-admin@example.com")

    response = await client.post(f"/api/content/modules/{module['id']}/remind")

    assert response.status_code == 200, response.text
    assert response.json()["sent_count"] == 1
    assert "remnudge-learner@example.com" in _reminder_emails_to(sent_emails)


async def test_the_manual_nudge_is_rate_limited_to_once_per_module_per_day(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remrate-author@example.com")
    group = await _make_group(db_session, name="RemRate Group")
    learner = await _make_user_with_role(
        db_session, email="remrate-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(
        client, db_session, email="remrate-cm@example.com", role_name="Content Manager"
    )
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )
    await _switch_to_admin(client, db_session, email="remrate-admin@example.com")

    first = await client.post(f"/api/content/modules/{module['id']}/remind")
    second = await client.post(f"/api/content/modules/{module['id']}/remind")

    assert first.status_code == 200
    assert first.json()["sent_count"] == 1
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "reminder_already_sent_today"


async def test_the_manual_nudge_rate_limit_holds_even_when_nobody_is_reached(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    """The endpoint's own once-per-module-per-day limit is checked against the
    fact that it *ran*, not against whether it emailed anyone — otherwise a
    module where the scheduled job already reached everyone today could be
    nudged an unlimited number of times, each call correctly sending zero
    emails but never itself getting rate-limited.
    """
    today = await _today(db_session)
    module = await _create_module(client, db_session, author_email="remzero-author@example.com")
    group = await _make_group(db_session, name="RemZero Group")
    learner = await _make_user_with_role(
        db_session, email="remzero-learner@example.com", role_name="Learner"
    )
    await _add_to_group(db_session, learner, group)
    await _login_with_role(client, db_session, email="remzero-cm@example.com", role_name="Content Manager")
    await _assign(
        client, module_id=module["id"], target_type="group", target_id=group.id, due_date=today
    )

    # The scheduled job reaches the one outstanding learner first, so the
    # manual nudge that follows has nobody left to email.
    scheduled_count = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()
    assert scheduled_count == 1

    await _switch_to_admin(client, db_session, email="remzero-admin@example.com")
    first = await client.post(f"/api/content/modules/{module['id']}/remind")
    second = await client.post(f"/api/content/modules/{module['id']}/remind")

    assert first.status_code == 200
    assert first.json()["sent_count"] == 0
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "reminder_already_sent_today"


async def _switch_to_admin(client: AsyncClient, db_session: AsyncSession, *, email: str) -> None:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login_with_role(client, db_session, email=email, role_name="Administrator")


# --- The deployment timezone setting -----------------------------------------


async def test_an_administrator_can_read_and_set_the_reminder_timezone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tzsetting-admin@example.com", role_name="Administrator"
    )

    default = await client.get("/api/admin/settings/reminder-timezone")
    assert default.status_code == 200
    assert default.json()["timezone"] == "Europe/Berlin"

    updated = await client.put(
        "/api/admin/settings/reminder-timezone", json={"timezone": "America/New_York"}
    )
    assert updated.status_code == 200
    assert updated.json()["timezone"] == "America/New_York"

    confirmed = await client.get("/api/admin/settings/reminder-timezone")
    assert confirmed.json()["timezone"] == "America/New_York"


async def test_an_invalid_timezone_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tzinvalid-admin@example.com", role_name="Administrator"
    )

    response = await client.put(
        "/api/admin/settings/reminder-timezone", json={"timezone": "Not/AZone"}
    )

    assert response.status_code == 422


async def test_a_content_manager_cannot_set_the_reminder_timezone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tzforbidden-cm@example.com", role_name="Content Manager"
    )

    response = await client.put(
        "/api/admin/settings/reminder-timezone", json={"timezone": "UTC"}
    )

    assert response.status_code == 403

"""Campaign reminders (Release 2, ticket 7).

What this file holds down: a learner is chased once per campaign, with one email
listing the mandatory modules they still owe, on the existing cadence; the
send log is shared with Release 1's per-module reminders in both directions;
suspended and closed campaigns send nothing and a resume produces no catch-up;
and the Administrator's manual nudge is Administrator-only and limited to once
per campaign per day.

Like `test_reminders.py`, the scheduled path has no route, so it is called
directly against `db_session`, with the reminder timezone pinned to UTC.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, CampaignReminder, Module, ModuleProgress
from app.reminders import (
    run_scheduled_campaign_reminders,
    run_scheduled_reminders,
)
from tests.conftest import FakeSESClient
from tests.test_assignments import _add_to_group, _make_user_with_role
from tests.test_campaign_activation import _campaign
from tests.test_campaigns import _as
from tests.test_reminders import _assign, _complete, _today

BASE = "/api/content/campaigns"


def _campaign_mails(sent_emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e
        for e in sent_emails
        if "campaign training" in e["Message"]["Subject"]["Data"]
        or "Kampagnentraining" in e["Message"]["Subject"]["Data"]
    ]


def _body(email: dict[str, Any]) -> str:
    return email["Message"]["Body"]["Text"]["Data"]


async def _live_campaign(
    client: AsyncClient,
    db: AsyncSession,
    tag: str,
    *,
    due_in: int | None,
    learners: int = 1,
    mandatory: int = 1,
    language: str | None = None,
    **overrides: Any,
) -> tuple[dict[str, Any], list[str], list[Any]]:
    """An active campaign, due `due_in` days from today, with learners in its group."""
    today = await _today(db)
    if due_in is not None:
        overrides["due_date"] = (today + timedelta(days=due_in)).isoformat()
    campaign, groups, group = await _campaign(client, db, tag, mandatory=mandatory, **overrides)
    users = []
    for i in range(learners):
        user = await _make_user_with_role(
            db, email=f"{tag}-l{i}@example.com", role_name="Learner", preferred_language=language
        )
        await _add_to_group(db, user, group)
        users.append(user)
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200
    return campaign, groups, users


async def _run(db: AsyncSession, sent_emails: list[dict[str, Any]]) -> int:
    sent = await run_scheduled_campaign_reminders(db, FakeSESClient(sent_emails))
    await db.commit()
    return sent


async def _module_of(db: AsyncSession, group_id: str) -> Module:
    return (
        await db.execute(select(Module).where(Module.translation_group_id == uuid.UUID(group_id)))
    ).scalar_one()


# --- Cadence and content ------------------------------------------------------


async def test_one_email_per_learner_lists_every_owed_mandatory_module(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _live_campaign(client, db_session, "cr1", due_in=7, learners=2, mandatory=3)
    sent_emails.clear()

    assert await _run(db_session, sent_emails) == 2

    mails = _campaign_mails(sent_emails)
    assert len(mails) == 2
    for mail in mails:
        assert all(f"cr1 M{i}" in _body(mail) for i in range(3))
        assert "cr1 campaign" in _body(mail)


async def test_recommended_modules_are_never_chased(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    campaign, groups, group = await _campaign(client, db_session, "cr2", mandatory=2)
    await client.patch(
        f"{BASE}/{campaign['id']}",
        json={
            "due_date": (today + timedelta(days=1)).isoformat(),
            "modules": [
                {"translation_group_id": groups[0], "requirement": "mandatory"},
                {"translation_group_id": groups[1], "requirement": "recommended"},
            ],
        },
    )
    learner = await _make_user_with_role(db_session, email="cr2-l@example.com", role_name="Learner")
    await _add_to_group(db_session, learner, group)
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200
    sent_emails.clear()

    await _run(db_session, sent_emails)

    (mail,) = _campaign_mails(sent_emails)
    assert "cr2 M0" in _body(mail) and "cr2 M1" not in _body(mail)


async def test_cadence_checkpoints_and_off_days(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    for tag, due_in, expected in [
        ("cr3a", 7, 1), ("cr3b", 1, 1), ("cr3c", 0, 1), ("cr3d", -14, 1),
        ("cr3e", 3, 0), ("cr3f", -3, 0), ("cr3g", 30, 0),
    ]:
        await _live_campaign(client, db_session, tag, due_in=due_in)
        sent_emails.clear()
        sent = await run_scheduled_campaign_reminders(db_session, FakeSESClient(sent_emails))
        await db_session.commit()
        # Earlier loop iterations' campaigns are still active; count only this one's mail.
        mine = [m for m in _campaign_mails(sent_emails) if f"{tag}-l0@example.com" in str(m["Destination"])]
        assert len(mine) == expected, (tag, sent)
        # Their log rows from this iteration must not leak into the next.
        for row in (await db_session.execute(select(CampaignReminder))).scalars():
            await db_session.delete(row)
        await db_session.commit()


async def test_completed_learners_are_skipped_and_a_superseded_completion_is_owed(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    _, groups, (done, superseded, fresh) = await _live_campaign(
        client, db_session, "cr4", due_in=1, learners=3
    )
    module = await _module_of(db_session, groups[0])
    for user in (done, superseded):
        await _complete(
            db_session, user_id=user.id, translation_group_id=module.translation_group_id,
            module_id=module.id,
        )
    row = (
        await db_session.execute(select(ModuleProgress).where(ModuleProgress.user_id == superseded.id))
    ).scalar_one()
    row.superseded_at = datetime.now(UTC)
    await db_session.commit()
    sent_emails.clear()

    assert await _run(db_session, sent_emails) == 2
    recipients = {m["Destination"]["ToAddresses"][0] for m in _campaign_mails(sent_emails)}
    assert recipients == {superseded.email, fresh.email}


async def test_email_is_rendered_in_the_learners_language(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _live_campaign(client, db_session, "cr5", due_in=1, language="de")
    sent_emails.clear()

    await _run(db_session, sent_emails)

    (mail,) = _campaign_mails(sent_emails)
    assert "Erinnerung" in mail["Message"]["Subject"]["Data"]
    assert "morgen fällig" in _body(mail)


async def test_no_reminder_without_auto_reminders_or_a_due_date(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _live_campaign(client, db_session, "cr6a", due_in=1, auto_reminders=False)
    await _live_campaign(client, db_session, "cr6b", due_in=None)
    sent_emails.clear()

    assert await _run(db_session, sent_emails) == 0
    assert _campaign_mails(sent_emails) == []


# --- The cap and the shared send log -------------------------------------------


async def test_a_second_run_the_same_day_sends_nothing(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _live_campaign(client, db_session, "cr7", due_in=1)
    sent_emails.clear()

    assert await _run(db_session, sent_emails) == 1
    assert await _run(db_session, sent_emails) == 0
    assert len(_campaign_mails(sent_emails)) == 1


async def test_a_module_reminder_is_suppressed_on_a_day_the_campaign_covered_it(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    _, groups, (learner,) = await _live_campaign(client, db_session, "cr8", due_in=1)
    module = await _module_of(db_session, groups[0])
    # The same learner also has a Release 1 assignment on the same material.
    await _as(client, db_session, "cr8-cm2@example.com", "Content Manager")
    await _assign(
        client, module_id=str(module.id), target_type="group",
        target_id=(await _group_of(db_session, learner)), due_date=today + timedelta(days=1),
    )
    sent_emails.clear()

    campaign_sent = await run_scheduled_campaign_reminders(db_session, FakeSESClient(sent_emails))
    module_sent = await run_scheduled_reminders(db_session, FakeSESClient(sent_emails))
    await db_session.commit()

    assert (campaign_sent, module_sent) == (1, 0)
    assert len(sent_emails) == 1


async def test_a_module_already_chased_today_is_left_off_the_campaign_email(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    _, groups, (learner,) = await _live_campaign(client, db_session, "cr9", due_in=1, mandatory=2)
    module = await _module_of(db_session, groups[0])
    await _as(client, db_session, "cr9-cm2@example.com", "Content Manager")
    await _assign(
        client, module_id=str(module.id), target_type="group",
        target_id=(await _group_of(db_session, learner)), due_date=today + timedelta(days=1),
    )
    sent_emails.clear()

    # The module path runs first this time.
    assert await run_scheduled_reminders(db_session, FakeSESClient(sent_emails)) == 1
    assert await _run(db_session, sent_emails) == 1

    (mail,) = _campaign_mails(sent_emails)
    assert "cr9 M1" in _body(mail) and "cr9 M0" not in _body(mail)


async def _group_of(db: AsyncSession, user: Any) -> uuid.UUID:
    from app.models import Group, group_members

    return (
        await db.execute(
            select(Group.id).join(group_members, group_members.c.group_id == Group.id).where(
                group_members.c.user_id == user.id
            )
        )
    ).scalar_one()


# --- Suspension, closure and resume ---------------------------------------------


async def test_suspended_and_closed_campaigns_send_nothing(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    suspended, _, _ = await _live_campaign(client, db_session, "cr10a", due_in=1)
    closed, _, _ = await _live_campaign(client, db_session, "cr10b", due_in=1)
    assert (await client.post(f"{BASE}/{closed['id']}/close")).status_code == 200
    await _as(client, db_session, "cr10a-cm2@example.com", "Administrator")
    assert (await client.post(f"{BASE}/{suspended['id']}/suspend")).status_code == 200
    sent_emails.clear()

    assert await _run(db_session, sent_emails) == 0


async def test_resuming_sends_no_catch_up_and_the_next_cadence_step_applies(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    today = await _today(db_session)
    campaign, _, _ = await _live_campaign(client, db_session, "cr11", due_in=7)
    assert (await client.post(f"{BASE}/{campaign['id']}/suspend")).status_code == 200
    sent_emails.clear()
    assert await _run(db_session, sent_emails) == 0  # the day-7 checkpoint passes in silence

    assert (await client.post(f"{BASE}/{campaign['id']}/resume")).status_code == 200
    # Resumed on an off-cadence day (due is still 7 days off, which *is* a
    # checkpoint) — move the date so today is between checkpoints.
    assert (
        await client.patch(
            f"{BASE}/{campaign['id']}", json={"due_date": (today + timedelta(days=4)).isoformat()}
        )
    ).status_code == 200
    assert await _run(db_session, sent_emails) == 0  # no burst for the missed step

    assert (
        await client.patch(
            f"{BASE}/{campaign['id']}", json={"due_date": (today + timedelta(days=1)).isoformat()}
        )
    ).status_code == 200
    assert await _run(db_session, sent_emails) == 1  # the next step applies


# --- Manual nudge --------------------------------------------------------------


async def test_manual_nudge_is_administrator_only_and_reports_the_real_reach(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, _, _ = await _live_campaign(client, db_session, "cr12", due_in=20, learners=2)
    sent_emails.clear()

    forbidden = await client.post(f"{BASE}/{campaign['id']}/remind")
    assert forbidden.status_code == 403  # still logged in as the Content Manager

    await _as(client, db_session, "cr12-admin@example.com", "Administrator")
    response = await client.post(f"{BASE}/{campaign['id']}/remind")
    assert response.status_code == 200, response.text
    assert response.json() == {"sent_count": 2}
    assert len(_campaign_mails(sent_emails)) == 2
    entries = [
        e
        for e in (await db_session.execute(select(AuditLog).where(AuditLog.action == "reminder_sent"))).scalars()
        if e.detail.get("campaign_id") == campaign["id"]
    ]
    assert len(entries) == 1 and entries[0].detail["sent_count"] == 2


async def test_manual_nudge_is_limited_to_once_per_campaign_per_day(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, _, _ = await _live_campaign(client, db_session, "cr13", due_in=20)
    await _as(client, db_session, "cr13-admin@example.com", "Administrator")
    assert (await client.post(f"{BASE}/{campaign['id']}/remind")).status_code == 200
    sent_emails.clear()

    second = await client.post(f"{BASE}/{campaign['id']}/remind")

    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "reminder_already_sent_today"
    assert sent_emails == []


async def test_a_zero_reach_nudge_still_counts_against_the_daily_limit(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, _, _ = await _live_campaign(client, db_session, "cr14", due_in=1)
    await _run(db_session, sent_emails)  # the scheduled run already reached everyone today
    await _as(client, db_session, "cr14-admin@example.com", "Administrator")

    first = await client.post(f"{BASE}/{campaign['id']}/remind")
    second = await client.post(f"{BASE}/{campaign['id']}/remind")

    assert first.json() == {"sent_count": 0}
    assert second.status_code == 429


async def test_manual_nudge_refuses_non_active_campaigns_and_unknown_ids(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    campaign, _, _ = await _live_campaign(client, db_session, "cr15", due_in=1)
    await _as(client, db_session, "cr15-admin@example.com", "Administrator")
    assert (await client.post(f"{BASE}/{campaign['id']}/suspend")).status_code == 200
    sent_emails.clear()

    refused = await client.post(f"{BASE}/{campaign['id']}/remind")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "campaign_not_active"
    assert (await client.post(f"{BASE}/{uuid.uuid4()}/remind")).status_code == 404
    assert sent_emails == []



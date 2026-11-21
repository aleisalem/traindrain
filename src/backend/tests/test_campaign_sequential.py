"""Sequential campaigns (Release 2, ticket 5).

What this file holds down: in a sequential campaign module N is unreachable
until module N-1 is a current completion — by URL, by page view, by
attestation and by asset delivery — a learner who reaches the module another
way is not locked, a superseded completion relocks, and the learner API says
what is locked and what unlocks it.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, ModuleProgress
from app.routes.assets import authorize_asset_access
from tests.test_assignments import _add_to_group, _login, _switch_to
from tests.test_campaign_activation import _campaign, _read_all_and_complete

BASE = "/api/content/campaigns"


async def _sequential(
    client: AsyncClient, db: AsyncSession, tag: str, *, mandatory: int = 3
) -> tuple[dict, list[str], object]:
    campaign, groups, group = await _campaign(
        client, db, tag, mandatory=mandatory, sequential=True
    )
    assert (await client.post(f"{BASE}/{campaign['id']}/activate")).status_code == 200
    return campaign, groups, group


async def _module_of(db: AsyncSession, group_id: str) -> Module:
    return (
        await db.execute(select(Module).where(Module.translation_group_id == uuid.UUID(group_id)))
    ).scalar_one()


def _row(campaigns: list[dict], group_id: str) -> dict:
    return next(
        m for c in campaigns for m in c["modules"] if m["translation_group_id"] == group_id
    )


async def test_a_module_is_locked_until_its_predecessor_is_complete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, groups, group = await _sequential(client, db_session, "seq1")
    learner = await _switch_to(client, db_session, email="seq1-l@example.com")
    await _add_to_group(db_session, learner, group)

    # First module is open; the rest are locked, each naming its own predecessor.
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200
    for i in (1, 2):
        locked = await client.get(f"/api/me/modules/{groups[i]}")
        assert locked.status_code == 403
        detail = locked.json()["detail"]
        assert detail["code"] == "module_locked"
        assert detail["prerequisite_translation_group_id"] == groups[i - 1]
        # The locked response carries no pages.
        assert "pages" not in detail

    campaigns = (await client.get("/api/me/campaigns")).json()
    assert campaigns[0]["sequential"] is True
    assert _row(campaigns, groups[0])["locked"] is False
    second = _row(campaigns, groups[1])
    assert second["locked"] is True and second["available"] is False
    assert second["prerequisite_translation_group_id"] == groups[0]
    assert second["prerequisite_title"] == "seq1 M0"

    await _read_all_and_complete(client, groups[0])
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 200
    assert (await client.get(f"/api/me/modules/{groups[2]}")).status_code == 403
    campaigns = (await client.get("/api/me/campaigns")).json()
    assert _row(campaigns, groups[1])["locked"] is False
    assert _row(campaigns, groups[2])["locked"] is True


async def test_a_locked_module_refuses_page_views_and_attestation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, groups, group = await _sequential(client, db_session, "seq2", mandatory=2)
    learner = await _switch_to(client, db_session, email="seq2-l@example.com")
    await _add_to_group(db_session, learner, group)

    page_id = str(uuid.uuid4())
    view = await client.post(f"/api/me/modules/{groups[1]}/pages/{page_id}/view")
    assert view.status_code == 403
    assert (await client.post(f"/api/me/modules/{groups[1]}/complete")).status_code == 403
    assert (
        await client.post(f"/api/me/modules/{groups[1]}/language", json={"language": "en"})
    ).status_code == 404
    rows = (await db_session.execute(select(ModuleProgress))).scalars().all()
    assert all(str(r.translation_group_id) != groups[1] for r in rows)


async def test_a_locked_modules_assets_are_not_served(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, groups, group = await _sequential(client, db_session, "seq3", mandatory=2)
    learner = await _switch_to(client, db_session, email="seq3-l@example.com")
    await _add_to_group(db_session, learner, group)
    locked, first = await _module_of(db_session, groups[1]), await _module_of(db_session, groups[0])

    with pytest.raises(HTTPException) as refused:
        await authorize_asset_access(db_session, learner, locked)
    assert refused.value.status_code == 404
    await authorize_asset_access(db_session, learner, first)

    await _read_all_and_complete(client, groups[0])
    await authorize_asset_access(db_session, learner, locked)


async def test_a_superseded_completion_relocks_the_next_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, groups, group = await _sequential(client, db_session, "seq4", mandatory=2)
    learner = await _switch_to(client, db_session, email="seq4-l@example.com")
    await _add_to_group(db_session, learner, group)
    await _read_all_and_complete(client, groups[0])
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 200

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == learner.id,
                ModuleProgress.translation_group_id == uuid.UUID(groups[0]),
            )
        )
    ).scalar_one()
    progress.superseded_at = datetime.now(UTC)
    await db_session.commit()

    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 403
    await _read_all_and_complete(client, groups[0])  # re-attest after re-reading
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 200


async def test_another_route_is_not_locked_by_the_campaign(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, groups, group = await _sequential(client, db_session, "seq5", mandatory=2)
    module = await _module_of(db_session, groups[1])
    module.catalog_visible = True
    await db_session.commit()
    learner = await _switch_to(client, db_session, email="seq5-l@example.com")
    await _add_to_group(db_session, learner, group)

    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 200
    row = _row((await client.get("/api/me/campaigns")).json(), groups[1])
    assert row["locked"] is False and row["available"] is True


async def test_a_non_sequential_campaign_locks_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _campaign(client, db_session, "seq6", mandatory=2)
    await client.post(f"{BASE}/{campaign['id']}/activate")
    learner = await _switch_to(client, db_session, email="seq6-l@example.com")
    await _add_to_group(db_session, learner, group)
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 200
    campaigns = (await client.get("/api/me/campaigns")).json()
    assert campaigns[0]["sequential"] is False
    assert not any(m["locked"] for m in campaigns[0]["modules"])


async def test_an_unpublished_predecessor_does_not_lock_the_campaign_forever(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, groups, group = await _sequential(client, db_session, "seq7", mandatory=3)
    # Withdraw the middle module: nobody can complete it.
    middle = await _module_of(db_session, groups[1])
    middle.status = "draft"
    await db_session.commit()
    learner = await _switch_to(client, db_session, email="seq7-l@example.com")
    await _add_to_group(db_session, learner, group)

    # The third waits on the first (nearest module that can still be completed).
    locked = await client.get(f"/api/me/modules/{groups[2]}")
    assert locked.status_code == 403
    assert locked.json()["detail"]["prerequisite_translation_group_id"] == groups[0]
    await _read_all_and_complete(client, groups[0])
    assert (await client.get(f"/api/me/modules/{groups[2]}")).status_code == 200


async def test_a_closed_sequential_campaign_keeps_what_was_started(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    campaign, groups, group = await _sequential(client, db_session, "seq8", mandatory=2)
    learner = await _switch_to(client, db_session, email="seq8-l@example.com")
    await _add_to_group(db_session, learner, group)
    await _read_all_and_complete(client, groups[0])
    await _login(client, email="seq8-cm@example.com")
    assert (await client.post(f"{BASE}/{campaign['id']}/close")).status_code == 200
    await _login(client, email="seq8-l@example.com")
    assert (await client.get(f"/api/me/modules/{groups[0]}")).status_code == 200
    # Closing stops new starts; the lock is not what refuses this one.
    assert (await client.get(f"/api/me/modules/{groups[1]}")).status_code == 404

"""What `substantive` actually costs a learner.

An author publishing a revision answers one question: does everybody have to
read this again? This file holds down that the answer is acted on rather than
merely filed.

The property that matters most here is the second half of it. Marking a
completion superseded re-opens the attestation, and a page keeps its id across
an edit — so a learner whose viewed-page ids were left in place could satisfy
the "read every page first" check with pages they read in the *previous*
version, walk to the last page, and confirm having read material they have
never seen. `test_a_superseded_learner_cannot_simply_confirm_again` is the one
that would fail if that hole reopened.

The mirror property is that `minor` costs nothing: an author fixing a typo must
not be able to send an organisation back through a module by accident.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, ModuleProgress, User
from tests.test_learner_viewer import (
    _add_page,
    _become_learner,
    _login,
    _login_with_role,
    _open,
    _publish_module,
    _view_every_page,
)


async def _sign_in_as(client: AsyncClient, *, email: str) -> None:
    """Hand the client to somebody who already exists.

    Distinct from `_become_learner`, which *creates* the learner: these tests
    move back and forth between one author and one learner, and re-creating
    either of them would be a different person with the same name.
    """
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=email)


async def _republish(
    client: AsyncClient, module_id: str, *, kind: str, revision: int
) -> dict[str, Any]:
    """Rewrite the material, then publish that rewrite as `kind`."""
    await _add_page(client, module_id, title="What changed", revision=revision)
    response = await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": kind}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _complete(client: AsyncClient, group_id: str) -> dict[str, Any]:
    """Read every page of what is published now, then attest to it."""
    opened = await _open(client, group_id)
    assert opened.status_code == 200, opened.text
    module = opened.json()
    await _view_every_page(client, group_id, module["pages"])
    response = await client.post(f"/api/me/modules/{group_id}/complete")
    assert response.status_code == 200, response.text
    return response.json()


async def _progress(db_session: AsyncSession, learner: User) -> ModuleProgress:
    return (
        await db_session.execute(
            select(ModuleProgress).where(ModuleProgress.user_id == learner.id)
        )
    ).scalar_one()


async def _completed_learner(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    slug: str,
) -> tuple[str, str, User, dict[str, Any]]:
    """An author with a published module and a learner who has completed it.

    Returns the module id, its translation group id, the learner, and the
    completion the learner was given.
    """
    author_email = f"{slug}-author@example.com"
    module = await _publish_module(client, db_session, author_email=author_email)
    group_id = module["translation_group_id"]

    learner = await _become_learner(client, db_session, email=f"{slug}-learner@example.com")
    completion = await _complete(client, group_id)
    assert completion["completed_version_number"] == 1
    assert completion["superseded_at"] is None

    await _sign_in_as(client, email=author_email)
    return module["id"], group_id, learner, completion


# --- What a substantive republish does to a finished learner --------------


async def test_a_substantive_republish_supersedes_a_completed_learner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id, group_id, learner, completion = await _completed_learner(
        client, db_session, slug="supersede"
    )

    await _republish(client, module_id, kind="substantive", revision=3)

    progress = await _progress(db_session, learner)
    await db_session.refresh(progress)
    assert progress.superseded_at is not None
    # The past is not rewritten: they did read version 1, on the day they did.
    assert progress.completed_at is not None
    assert progress.completed_at.isoformat() == completion["completed_at"].replace("Z", "+00:00")
    assert progress.completed_version_number == 1


async def test_a_superseded_learner_cannot_simply_confirm_again(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The point of the whole feature.

    Page ids survive an edit, so the ids this learner viewed in version 1 name
    every page of version 2 as well. If the republish left `pages_viewed`
    alone, this attestation would succeed without a page of the new text being
    opened — the learner would be confirming they had read something they had
    not.
    """
    module_id, group_id, learner, _ = await _completed_learner(
        client, db_session, slug="no-free-confirm"
    )

    await _republish(client, module_id, kind="substantive", revision=3)

    await _sign_in_as(client, email="no-free-confirm-learner@example.com")
    refused = await client.post(f"/api/me/modules/{group_id}/complete")

    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "pages_outstanding"
    # Every page of the new version, not merely the page that was added.
    assert detail["pages_outstanding"] == 3
    assert detail["pages_total"] == 3


async def test_the_superseded_learner_is_told_so_when_they_reopen_the_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id, group_id, _, _ = await _completed_learner(client, db_session, slug="reopen")

    await _republish(client, module_id, kind="substantive", revision=3)

    await _sign_in_as(client, email="reopen-learner@example.com")
    body = (await _open(client, group_id)).json()

    assert body["version_number"] == 2
    assert body["progress"]["superseded_at"] is not None
    # Back at the beginning, with nothing counted towards the new text.
    assert body["progress"]["pages_viewed"] == []
    assert body["progress"]["current_page_id"] is None
    # And the completion they earned is still on the record.
    assert body["progress"]["completed_at"] is not None
    assert body["progress"]["completed_version_number"] == 1


async def test_reading_the_new_version_and_attesting_again_clears_the_supersede(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The way out. Doing the work restores a current completion."""
    module_id, group_id, learner, _ = await _completed_learner(client, db_session, slug="redo")
    await _republish(client, module_id, kind="substantive", revision=3)

    await _sign_in_as(client, email="redo-learner@example.com")
    completion = await _complete(client, group_id)

    assert completion["superseded_at"] is None
    assert completion["completed_version_number"] == 2
    progress = await _progress(db_session, learner)
    await db_session.refresh(progress)
    assert progress.superseded_at is None


# --- What a minor republish does, which is nothing ------------------------


async def test_a_minor_republish_leaves_a_completed_learner_completed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id, group_id, learner, _ = await _completed_learner(client, db_session, slug="minor")

    await _republish(client, module_id, kind="minor", revision=3)

    progress = await _progress(db_session, learner)
    await db_session.refresh(progress)
    assert progress.superseded_at is None
    assert progress.completed_version_number == 1
    # Their reading is untouched, which is what "minor" promised.
    assert len(progress.pages_viewed) == 2
    assert progress.current_page_id is not None


async def test_a_minor_republish_does_not_reset_a_learner_who_is_part_way_through(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_email = "minor-midread-author@example.com"
    module = await _publish_module(client, db_session, author_email=author_email)
    group_id = module["translation_group_id"]

    learner = await _become_learner(
        client, db_session, email="minor-midread-learner@example.com"
    )
    pages = (await _open(client, group_id)).json()["pages"]
    await _view_every_page(client, group_id, pages[:1])

    await _sign_in_as(client, email=author_email)
    await _republish(client, module["id"], kind="minor", revision=3)

    progress = await _progress(db_session, learner)
    await db_session.refresh(progress)
    assert len(progress.pages_viewed) == 1
    assert progress.current_page_id is not None


# --- What it does to someone who was still reading ------------------------


async def test_a_substantive_republish_resets_a_learner_who_is_part_way_through(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The quieter version of the same hole.

    Somebody eight pages into version 1 has read eight pages that no longer say
    what they said. Letting those count towards attesting to version 2 is the
    same free confirmation by a slower route.
    """
    author_email = "midread-author@example.com"
    module = await _publish_module(client, db_session, author_email=author_email)
    group_id = module["translation_group_id"]

    learner = await _become_learner(client, db_session, email="midread-learner@example.com")
    pages = (await _open(client, group_id)).json()["pages"]
    await _view_every_page(client, group_id, pages[:1])

    await _sign_in_as(client, email=author_email)
    await _republish(client, module["id"], kind="substantive", revision=3)

    progress = await _progress(db_session, learner)
    await db_session.refresh(progress)
    assert progress.pages_viewed == []
    assert progress.current_page_id is None
    # Never completed, so there was no completion to supersede.
    assert progress.completed_at is None
    assert progress.superseded_at is None


# --- Where the learner sees it -------------------------------------------


async def test_my_learning_marks_the_module_superseded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id, _, _, _ = await _completed_learner(client, db_session, slug="mine")

    await _republish(client, module_id, kind="substantive", revision=3)

    await _sign_in_as(client, email="mine-learner@example.com")
    rows = (await client.get("/api/me/modules")).json()

    assert len(rows) == 1
    assert rows[0]["superseded_at"] is not None
    assert rows[0]["completed_at"] is not None


async def test_the_catalog_does_not_call_a_superseded_module_completed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A card saying "Completed" next to a module demanding to be re-read would
    be the catalog contradicting the module it links to."""
    module_id, _, _, _ = await _completed_learner(client, db_session, slug="catalog")

    await _republish(client, module_id, kind="substantive", revision=3)

    await _sign_in_as(client, email="catalog-learner@example.com")
    entries = (await client.get("/api/catalog/modules")).json()

    entry = next(item for item in entries if item["title"] == "Phishing Awareness")
    assert entry["completed_at"] is not None
    assert entry["superseded_at"] is not None


# --- What the author is told and what is recorded -------------------------


async def test_the_audit_entry_records_how_many_completions_were_superseded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id, _, _, _ = await _completed_learner(client, db_session, slug="audit")

    await _republish(client, module_id, kind="substantive", revision=3)

    entries = (
        await db_session.execute(
            select(AuditLog)
            .where(
                AuditLog.action == "module_published",
                AuditLog.detail["module_id"].astext == module_id,
            )
            .order_by(AuditLog.timestamp)
        )
    ).scalars().all()
    assert [entry.detail["revision_kind"] for entry in entries] == ["minor", "substantive"]
    assert entries[0].detail["superseded_completions"] == 0
    assert entries[1].detail["superseded_completions"] == 1


async def test_the_revision_impact_counts_who_a_substantive_publish_would_affect(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author_email = "impact-author@example.com"
    module = await _publish_module(client, db_session, author_email=author_email)
    group_id = module["translation_group_id"]

    # One learner finishes it.
    await _become_learner(client, db_session, email="impact-done@example.com")
    await _complete(client, group_id)
    # A second opens it and reads one page.
    await _become_learner(client, db_session, email="impact-midway@example.com")
    pages = (await _open(client, group_id)).json()["pages"]
    await _view_every_page(client, group_id, pages[:1])

    await _sign_in_as(client, email=author_email)
    body = (
        await client.get(f"/api/content/modules/{module['id']}/revision-impact")
    ).json()

    assert body == {"completed_learners": 1, "in_progress_learners": 1}


async def test_the_revision_impact_of_a_module_nobody_has_opened_is_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="impact-quiet@example.com")

    body = (
        await client.get(f"/api/content/modules/{module['id']}/revision-impact")
    ).json()

    assert body == {"completed_learners": 0, "in_progress_learners": 0}


async def test_a_learner_may_not_read_the_revision_impact(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="impact-closed@example.com")

    await _become_learner(client, db_session, email="impact-nosy@example.com")
    response = await client.get(f"/api/content/modules/{module['id']}/revision-impact")

    assert response.status_code == 403


@pytest.mark.parametrize("role_name", ["Content Manager", "Administrator"])
async def test_the_revision_impact_of_an_unknown_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession, role_name: str
) -> None:
    await _login_with_role(
        client,
        db_session,
        email=f"impact-unknown-{role_name.replace(' ', '-').lower()}@example.com",
        role_name=role_name,
    )

    response = await client.get(f"/api/content/modules/{uuid.uuid4()}/revision-impact")

    assert response.status_code == 404

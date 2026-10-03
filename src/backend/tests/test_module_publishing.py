"""Publishing, version snapshots, unpublishing, and duplication.

The property this file exists to hold down is the separation between the draft
an author edits and the frozen text a learner reads. Almost every test here is
some form of "prove the two did not touch": an edit after a publish, a second
publish, an unpublish, a duplicate.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import AuditLog, Module, ModuleAsset, ModulePage, ModuleVersion, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME
from tests.test_upload_sniffing import PNG

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(db_session: AsyncSession, *, email: str, role_name: str) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Cora",
        last_name="Manager",
        roles=[role],
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client: AsyncClient, *, email: str) -> None:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": KNOWN_PASSWORD}
    )
    client.cookies.set(COOKIE_NAME, response.cookies[COOKIE_NAME])


async def _login_with_role(
    client: AsyncClient, db_session: AsyncSession, *, email: str, role_name: str
) -> User:
    user = await _make_user_with_role(db_session, email=email, role_name=role_name)
    await _login(client, email=email)
    return user


def _doc(text_content: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text_content}]}],
    }


async def _make_module(client: AsyncClient, *, title: str = "Phishing Awareness") -> str:
    response = await client.post(
        "/api/content/modules",
        json={"title": title, "description": "How to spot a phish.", "language": "en"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _add_page(
    client: AsyncClient,
    module_id: str,
    *,
    title: str,
    revision: int,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": revision,
            "title": title,
            "schema_version": SCHEMA_VERSION,
            "body": body if body is not None else _doc(title),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _module_with_a_page(
    client: AsyncClient, db_session: AsyncSession, *, email: str
) -> str:
    await _login_with_role(client, db_session, email=email, role_name="Content Manager")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    return module_id


async def _publish(client: AsyncClient, module_id: str, *, kind: str = "minor") -> Any:
    return await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": kind}
    )


async def _snapshot(db_session: AsyncSession, module_id: str) -> dict[str, Any]:
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None and module.current_version_id is not None
    version = await db_session.get(ModuleVersion, module.current_version_id)
    assert version is not None
    return version.snapshot


# --- Publishing -----------------------------------------------------------


async def test_publishing_writes_a_version_and_points_the_module_at_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client, db_session, email="publish-first@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)

    response = await _publish(client, module_id, kind="minor")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "published"
    assert body["current_version_number"] == 1

    snapshot = await _snapshot(db_session, module_id)
    assert snapshot["title"] == "Phishing Awareness"
    assert snapshot["description"] == "How to spot a phish."
    assert snapshot["language"] == "en"
    assert [page["title"] for page in snapshot["pages"]] == ["Intro"]

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "module_published",
                AuditLog.detail["module_id"].astext == module_id,
            )
        )
    ).scalar_one()
    assert entry.actor_user_id == author.id
    assert entry.detail["version_number"] == 1
    assert entry.detail["revision_kind"] == "minor"


@pytest.mark.parametrize("kind", ["minor", "substantive"])
async def test_the_publish_records_the_revision_kind_the_author_chose(
    client: AsyncClient, db_session: AsyncSession, kind: str
) -> None:
    module_id = await _module_with_a_page(
        client, db_session, email=f"publish-kind-{kind}@example.com"
    )

    assert (await _publish(client, module_id, kind=kind)).status_code == 200

    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None and module.current_version_id is not None
    version = await db_session.get(ModuleVersion, module.current_version_id)
    assert version is not None
    assert version.revision_kind == kind


@pytest.mark.parametrize("payload", [{}, {"revision_kind": None}, {"revision_kind": "typo-fix"}])
async def test_publishing_without_deciding_minor_or_substantive_is_refused(
    client: AsyncClient, db_session: AsyncSession, payload: dict[str, Any]
) -> None:
    """There is no default. Whether everyone re-reads the material is the
    author's call, and omitting the field must not make it quietly."""
    module_id = await _module_with_a_page(
        client, db_session, email=f"publish-nodefault-{hash(str(payload))}@example.com"
    )

    response = await client.post(f"/api/content/modules/{module_id}/publish", json=payload)

    assert response.status_code == 422
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    assert module.status == "draft"


async def test_publishing_a_module_with_no_pages_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="publish-empty@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)

    response = await _publish(client, module_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "empty_module"


async def test_editing_the_draft_after_a_publish_leaves_the_published_snapshot_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(client, db_session, email="publish-draft@example.com")
    pages = (await _publish(client, module_id)).json()
    assert pages["current_version_number"] == 1

    listed = (await client.get(f"/api/content/modules/{module_id}/pages")).json()
    page_id = listed["pages"][0]["id"]
    edited = await client.patch(
        f"/api/content/modules/{module_id}/pages/{page_id}",
        json={
            "draft_revision": listed["draft_revision"],
            "title": "Intro, revised",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Rewritten while live."),
        },
    )
    assert edited.status_code == 200
    await client.patch(f"/api/content/modules/{module_id}", json={"title": "Renamed"})

    snapshot = await _snapshot(db_session, module_id)
    assert [page["title"] for page in snapshot["pages"]] == ["Intro"]
    assert snapshot["pages"][0]["body"] == _doc("Intro")
    assert snapshot["title"] == "Phishing Awareness"


async def test_a_second_publish_writes_a_second_version_and_repoints_the_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(client, db_session, email="publish-second@example.com")
    await _publish(client, module_id, kind="minor")
    first = await _snapshot(db_session, module_id)

    listed = (await client.get(f"/api/content/modules/{module_id}/pages")).json()
    await _add_page(client, module_id, title="Reporting", revision=listed["draft_revision"])
    response = await _publish(client, module_id, kind="substantive")

    assert response.status_code == 200
    assert response.json()["current_version_number"] == 2
    second = await _snapshot(db_session, module_id)
    assert [page["title"] for page in first["pages"]] == ["Intro"]
    assert [page["title"] for page in second["pages"]] == ["Intro", "Reporting"]

    versions = (
        await db_session.execute(
            select(ModuleVersion)
            .where(ModuleVersion.module_id == uuid.UUID(module_id))
            .order_by(ModuleVersion.version_number)
        )
    ).scalars()
    assert [version.version_number for version in versions] == [1, 2]


async def test_a_version_row_cannot_be_updated_once_written(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Enforced by the database, not by the routes that happen not to try.

    A version snapshot is the evidence of what a learner was made to read, and
    evidence that can be quietly edited afterwards is not evidence.
    """
    module_id = await _module_with_a_page(client, db_session, email="publish-frozen@example.com")
    await _publish(client, module_id)
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None

    with pytest.raises(Exception, match="immutable"):
        await db_session.execute(
            text("UPDATE module_versions SET revision_kind = 'substantive' WHERE id = :id"),
            {"id": module.current_version_id},
        )
    await db_session.rollback()


async def test_version_history_lists_every_publish_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(client, db_session, email="publish-history@example.com")
    await _publish(client, module_id, kind="minor")
    listed = (await client.get(f"/api/content/modules/{module_id}/pages")).json()
    await _add_page(client, module_id, title="Reporting", revision=listed["draft_revision"])
    await _publish(client, module_id, kind="substantive")

    response = await client.get(f"/api/content/modules/{module_id}/versions")

    assert response.status_code == 200
    history = response.json()
    assert [entry["version_number"] for entry in history] == [2, 1]
    assert [entry["revision_kind"] for entry in history] == ["substantive", "minor"]
    assert [entry["page_count"] for entry in history] == [2, 1]
    assert history[0]["published_by"]["display_name"] == "Cora Manager"
    # The title as it stood at publish time, so a rename doesn't rewrite history.
    assert history[0]["title"] == "Phishing Awareness"


async def test_a_module_that_has_never_been_published_has_no_versions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(client, db_session, email="publish-none@example.com")

    response = await client.get(f"/api/content/modules/{module_id}/versions")

    assert response.status_code == 200
    assert response.json() == []
    assert (await client.get(f"/api/content/modules/{module_id}")).json()[
        "current_version_number"
    ] is None


# --- Unpublishing ---------------------------------------------------------


async def test_unpublishing_returns_the_module_to_draft_without_destroying_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client, db_session, email="unpublish@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    await _publish(client, module_id)

    response = await client.post(f"/api/content/modules/{module_id}/unpublish")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    # The version it was at is deliberately still there and still pointed at,
    # so a completion record against it keeps resolving.
    assert body["current_version_number"] == 1
    assert (
        await db_session.execute(
            select(ModuleVersion).where(ModuleVersion.module_id == uuid.UUID(module_id))
        )
    ).scalars().all() != []
    pages = (await client.get(f"/api/content/modules/{module_id}/pages")).json()["pages"]
    assert [page["title"] for page in pages] == ["Intro"]

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "module_unpublished",
                AuditLog.detail["module_id"].astext == module_id,
            )
        )
    ).scalar_one()
    assert entry.actor_user_id == author.id
    assert entry.detail["version_number"] == 1


async def test_republishing_after_an_unpublish_writes_the_next_version(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(client, db_session, email="republish@example.com")
    await _publish(client, module_id)
    await client.post(f"/api/content/modules/{module_id}/unpublish")

    response = await _publish(client, module_id, kind="minor")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["current_version_number"] == 2


async def test_unpublishing_a_module_that_is_not_published_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(
        client, db_session, email="unpublish-draft@example.com"
    )

    response = await client.post(f"/api/content/modules/{module_id}/unpublish")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_published"


# --- Duplication ----------------------------------------------------------


async def test_a_duplicate_is_an_independent_draft_with_its_own_translation_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client, db_session, email="duplicate@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    await _add_page(client, module_id, title="Reporting", revision=2)
    await _publish(client, module_id)
    original = (await client.get(f"/api/content/modules/{module_id}")).json()

    response = await client.post(
        f"/api/content/modules/{module_id}/duplicate",
        json={"title": "Phishing Awareness (copy)"},
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["id"] != module_id
    assert copy["title"] == "Phishing Awareness (copy)"
    assert copy["description"] == "How to spot a phish."
    assert copy["language"] == "en"
    # A copy is new material, not a translation of the original.
    assert copy["translation_group_id"] != original["translation_group_id"]
    # Never published, whatever the original's status.
    assert copy["status"] == "draft"
    assert copy["current_version_number"] is None

    pages = (await client.get(f"/api/content/modules/{copy['id']}/pages")).json()["pages"]
    assert [page["title"] for page in pages] == ["Intro", "Reporting"]
    assert pages[0]["body"] == _doc("Intro")

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "module_duplicated",
                AuditLog.detail["module_id"].astext == copy["id"],
            )
        )
    ).scalar_one()
    assert entry.actor_user_id == author.id
    assert entry.detail["source_module_id"] == module_id


async def test_editing_a_duplicate_does_not_touch_the_original(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module_with_a_page(client, db_session, email="duplicate-edit@example.com")
    copy_id = (
        await client.post(f"/api/content/modules/{module_id}/duplicate", json={})
    ).json()["id"]

    listed = (await client.get(f"/api/content/modules/{copy_id}/pages")).json()
    await client.patch(
        f"/api/content/modules/{copy_id}/pages/{listed['pages'][0]['id']}",
        json={
            "draft_revision": listed["draft_revision"],
            "title": "Rewritten",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Different words."),
        },
    )
    await client.patch(f"/api/content/modules/{copy_id}", json={"title": "Something else"})

    original_pages = (await client.get(f"/api/content/modules/{module_id}/pages")).json()
    assert [page["title"] for page in original_pages["pages"]] == ["Intro"]
    assert original_pages["pages"][0]["body"] == _doc("Intro")
    original = (await client.get(f"/api/content/modules/{module_id}")).json()
    assert original["title"] == "Phishing Awareness"


async def test_a_duplicate_without_a_title_keeps_the_original_s_own(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The "(copy)" suffix is the caller's word to choose.

    A platform that ships in English and German has no business inventing one
    server-side in a single language.
    """
    module_id = await _module_with_a_page(client, db_session, email="duplicate-title@example.com")

    response = await client.post(f"/api/content/modules/{module_id}/duplicate", json={})

    assert response.status_code == 201
    assert response.json()["title"] == "Phishing Awareness"


async def test_a_duplicate_gets_its_own_copies_of_the_assets_and_pages_that_point_at_them(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    await _login_with_role(
        client, db_session, email="duplicate-assets@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    uploaded = await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    assert uploaded.status_code == 201
    asset = uploaded.json()["assets"][0]
    await _add_page(
        client,
        module_id,
        title="Illustrated",
        revision=1,
        body={
            "type": "doc",
            "content": [{"type": "image", "attrs": {"src": asset["url"], "alt": "A diagram"}}],
        },
    )

    copy_id = (
        await client.post(f"/api/content/modules/{module_id}/duplicate", json={})
    ).json()["id"]

    copied_assets = (await client.get(f"/api/content/modules/{copy_id}/assets")).json()["assets"]
    assert len(copied_assets) == 1
    assert copied_assets[0]["id"] != asset["id"]
    assert copied_assets[0]["original_filename"] == "diagram.png"
    assert copied_assets[0]["content_type"] == "image/png"

    # The copied page points at the copy's own asset, not the original's — so
    # deleting the original can never blank out the duplicate's pages.
    page = (await client.get(f"/api/content/modules/{copy_id}/pages")).json()["pages"][0]
    assert page["body"]["content"][0]["attrs"]["src"] == copied_assets[0]["url"]
    assert copied_assets[0]["referenced_by_pages"] == 1

    # And its own stored object, with the original's still in place.
    rows = (
        await db_session.execute(
            select(ModuleAsset).where(ModuleAsset.module_id == uuid.UUID(copy_id))
        )
    ).scalars()
    keys = [row.object_key for row in rows]
    assert keys == [f"modules/{copy_id}/assets/{copied_assets[0]['id']}"]
    assert keys[0] in stored_objects
    assert f"modules/{module_id}/assets/{asset['id']}" in stored_objects
    assert stored_objects[keys[0]]["Body"] == PNG


async def test_a_duplicate_repoints_links_to_attachments_not_just_embedded_images(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A page can *link* an attachment as well as embed an image.

    An asset URL is a site-relative path, which the schema permits in an
    `href`, and the assets panel shows the author exactly that URL. A copy
    whose links still point at the original breaks the same way a copy whose
    images do.
    """
    await _login_with_role(
        client, db_session, email="duplicate-links@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    uploaded = await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": "attachment"},
        files={"file": ("policy.pdf", b"%PDF-1.4\n%test\n", "application/octet-stream")},
    )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()["assets"][0]
    await _add_page(
        client,
        module_id,
        title="Read the policy",
        revision=1,
        body={
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "The policy",
                            "marks": [{"type": "link", "attrs": {"href": asset["url"]}}],
                        }
                    ],
                }
            ],
        },
    )

    copy_id = (
        await client.post(f"/api/content/modules/{module_id}/duplicate", json={})
    ).json()["id"]

    copied_asset = (await client.get(f"/api/content/modules/{copy_id}/assets")).json()["assets"][0]
    page = (await client.get(f"/api/content/modules/{copy_id}/pages")).json()["pages"][0]
    href = page["body"]["content"][0]["content"][0]["marks"][0]["attrs"]["href"]
    assert href == copied_asset["url"]
    assert module_id not in href


async def test_a_failed_object_copy_leaves_nothing_behind_in_the_store(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    """The rollback undoes the rows; it cannot reach into the object store.

    So a duplicate that dies half-way through copying has to take its own
    already-copied objects back, or a private bucket quietly accumulates files
    nothing can enumerate.
    """
    from app.dependencies import get_s3_client
    from app.main import app
    from tests.conftest import FakeS3Client

    await _login_with_role(
        client, db_session, email="duplicate-failure@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    for name in ("one.png", "two.png"):
        assert (
            await client.post(
                f"/api/content/modules/{module_id}/assets",
                data={"kind": "image"},
                files={"file": (name, PNG, "application/octet-stream")},
            )
        ).status_code == 201

    class FailsOnTheSecondCopy(FakeS3Client):
        def __init__(self, objects: dict[str, dict[str, Any]]) -> None:
            super().__init__(objects)
            self.copies = 0

        def copy_object(self, **kwargs: Any) -> dict[str, str]:
            self.copies += 1
            if self.copies > 1:
                raise RuntimeError("the object store said no")
            return super().copy_object(**kwargs)

    failing = FailsOnTheSecondCopy(stored_objects)
    # Cleared by the `client` fixture's own teardown.
    app.dependency_overrides[get_s3_client] = lambda: failing

    before = set(stored_objects)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/content/modules/{module_id}/duplicate", json={})

    # The originals are untouched and the half-finished copy left no residue.
    # (The *rows* are the transaction's problem, not this test's: `get_db`
    # closes its session on the way out, which rolls them back. The suite's
    # session is deliberately shared with the test and never closed, so
    # asserting on rows here would be asserting on the fixture.)
    assert set(stored_objects) == before
    assert failing.copies == 2


async def test_an_asset_a_published_version_depends_on_says_so_before_it_is_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Publishing creates a second referrer the draft cannot speak for.

    Delete the page from the draft and the asset looks unused — but the
    published snapshot still embeds it, and a snapshot is immutable, so the
    image would simply vanish from what learners are reading with no edit
    available to put it back. The author has to be told that before they
    confirm.
    """
    await _login_with_role(
        client, db_session, email="asset-in-version@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    uploaded = await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    asset = uploaded.json()["assets"][0]
    created = await _add_page(
        client,
        module_id,
        title="Illustrated",
        revision=1,
        body={
            "type": "doc",
            "content": [{"type": "image", "attrs": {"src": asset["url"], "alt": "A diagram"}}],
        },
    )
    assert (await _publish(client, module_id)).status_code == 200

    # The author removes the page from the draft. The published v1 still has it.
    page_id = created["pages"][0]["id"]
    removed = await client.request(
        "DELETE",
        f"/api/content/modules/{module_id}/pages/{page_id}",
        json={"draft_revision": created["draft_revision"]},
    )
    assert removed.status_code == 200

    listed = (await client.get(f"/api/content/modules/{module_id}/assets")).json()["assets"][0]
    assert listed["referenced_by_pages"] == 0
    assert listed["referenced_by_versions"] == 1


async def test_duplicating_a_module_with_no_pages_or_assets_works(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="duplicate-empty@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)

    response = await client.post(f"/api/content/modules/{module_id}/duplicate", json={})

    assert response.status_code == 201
    copy_id = response.json()["id"]
    assert (
        await db_session.execute(
            select(ModulePage).where(ModulePage.module_id == uuid.UUID(copy_id))
        )
    ).scalars().all() == []


# --- Authorization --------------------------------------------------------


# Each route with a body its own request schema accepts, so an authorization
# or existence check is what the response is about rather than validation.
LIFECYCLE_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "publish", {"revision_kind": "minor"}),
    ("POST", "unpublish", {}),
    ("POST", "duplicate", {}),
    ("GET", "versions", {}),
]


@pytest.mark.parametrize(("method", "action", "payload"), LIFECYCLE_ROUTES)
async def test_a_learner_is_forbidden_from_every_lifecycle_route(
    client: AsyncClient, db_session: AsyncSession, method: str, action: str, payload: dict[str, Any]
) -> None:
    await _login_with_role(
        client, db_session, email=f"learner-{action}@example.com", role_name="Learner"
    )

    response = await client.request(
        method,
        f"/api/content/modules/{uuid.uuid4()}/{action}",
        json=payload,
    )

    assert response.status_code == 403


@pytest.mark.parametrize(("method", "action", "payload"), LIFECYCLE_ROUTES)
async def test_an_anonymous_visitor_is_unauthenticated_on_every_lifecycle_route(
    client: AsyncClient, method: str, action: str, payload: dict[str, Any]
) -> None:
    response = await client.request(
        method,
        f"/api/content/modules/{uuid.uuid4()}/{action}",
        json=payload,
    )

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "action", "payload"), LIFECYCLE_ROUTES)
async def test_an_unknown_module_is_a_404_on_every_lifecycle_route(
    client: AsyncClient, db_session: AsyncSession, method: str, action: str, payload: dict[str, Any]
) -> None:
    await _login_with_role(
        client, db_session, email=f"cm-missing-{action}@example.com", role_name="Content Manager"
    )

    response = await client.request(
        method,
        f"/api/content/modules/{uuid.uuid4()}/{action}",
        json=payload,
    )

    assert response.status_code == 404


async def test_an_administrator_can_publish(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="admin-publish@example.com", role_name="Administrator"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)

    assert (await _publish(client, module_id)).status_code == 200

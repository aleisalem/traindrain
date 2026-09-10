"""The learner's side: the open catalog, the viewer, progress, and attestation.

Two properties this file exists to hold down.

The first is access: material an author never opened to everyone is genuinely
unreachable, not merely absent from a list — and the same is true of the images
and attachments inside it, which are a second door into the same room.

The second is that the attestation means something. It is the one thing in this
release a learner asserts about themselves, and it is refused until every page
of the version they are reading has actually been opened.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import ModuleProgress, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME
from tests.test_upload_sniffing import PDF, PNG

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(db_session: AsyncSession, *, email: str, role_name: str) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Lena",
        last_name="Learner",
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


def _doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def _add_page(client: AsyncClient, module_id: str, *, title: str, revision: int) -> None:
    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": revision,
            "title": title,
            "schema_version": SCHEMA_VERSION,
            "body": _doc(f"The text of {title}."),
        },
    )
    assert response.status_code == 201, response.text


async def _publish_module(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    author_email: str,
    pages: tuple[str, ...] = ("Intro", "Details"),
    catalog_visible: bool = True,
    title: str = "Phishing Awareness",
) -> dict[str, Any]:
    """An author's whole job, start to finish, so a learner has something to read."""
    await _login_with_role(client, db_session, email=author_email, role_name="Content Manager")
    created = await client.post(
        "/api/content/modules",
        json={"title": title, "description": "How to spot a phish.", "language": "en"},
    )
    assert created.status_code == 201
    module = created.json()

    for revision, page_title in enumerate(pages, start=1):
        await _add_page(client, module["id"], title=page_title, revision=revision)

    if catalog_visible:
        patched = await client.patch(
            f"/api/content/modules/{module['id']}", json={"catalog_visible": True}
        )
        assert patched.status_code == 200
        assert patched.json()["catalog_visible"] is True

    published = await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
    )
    assert published.status_code == 200, published.text
    return published.json()


async def _become_learner(client: AsyncClient, db_session: AsyncSession, *, email: str) -> User:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db_session, email=email, role_name="Learner")


async def _open(client: AsyncClient, group_id: str) -> Any:
    return await client.get(f"/api/me/modules/{group_id}")


async def _view_every_page(client: AsyncClient, group_id: str, pages: list[dict[str, Any]]) -> None:
    for page in pages:
        response = await client.post(
            f"/api/me/modules/{group_id}/pages/{page['id']}/view"
        )
        assert response.status_code == 200, response.text


# --- The open catalog -----------------------------------------------------


async def test_the_catalog_lists_a_published_catalog_visible_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="cat-author@example.com")
    await _become_learner(client, db_session, email="cat-learner@example.com")

    response = await client.get("/api/catalog/modules")

    assert response.status_code == 200
    entries = [
        entry
        for entry in response.json()
        if entry["translation_group_id"] == module["translation_group_id"]
    ]
    assert len(entries) == 1
    assert entries[0]["title"] == "Phishing Awareness"
    assert entries[0]["page_count"] == 2
    assert entries[0]["started"] is False
    assert entries[0]["completed_at"] is None


async def test_a_module_the_author_never_opened_to_everyone_is_not_in_the_catalog(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Implicit deny, as a default on the column rather than a decision to remember."""
    module = await _publish_module(
        client, db_session, author_email="hidden-author@example.com", catalog_visible=False
    )
    assert module["catalog_visible"] is False
    await _become_learner(client, db_session, email="hidden-learner@example.com")

    response = await client.get("/api/catalog/modules")

    assert module["translation_group_id"] not in {
        entry["translation_group_id"] for entry in response.json()
    }


async def test_an_unpublished_module_is_not_in_the_catalog(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="unpub-author@example.com")
    unpublished = await client.post(f"/api/content/modules/{module['id']}/unpublish")
    assert unpublished.status_code == 200
    await _become_learner(client, db_session, email="unpub-learner@example.com")

    response = await client.get("/api/catalog/modules")

    assert module["translation_group_id"] not in {
        entry["translation_group_id"] for entry in response.json()
    }


async def test_the_catalog_needs_a_session(client: AsyncClient) -> None:
    client.cookies.clear()
    assert (await client.get("/api/catalog/modules")).status_code == 401


# --- Opening a module -----------------------------------------------------


async def test_a_learner_opens_a_catalog_module_and_reads_the_published_snapshot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="open-author@example.com")
    await _become_learner(client, db_session, email="open-learner@example.com")

    response = await _open(client, module["translation_group_id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Phishing Awareness"
    assert body["version_number"] == 1
    assert [page["title"] for page in body["pages"]] == ["Intro", "Details"]
    # Nothing recorded yet: opening a module is a read, and the record starts
    # when they read a page.
    assert body["progress"] is None


async def test_opening_a_module_records_nothing_until_a_page_is_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A GET is a read. A stray click on the wrong catalog card must not put a
    module on somebody's training history."""
    module = await _publish_module(client, db_session, author_email="peek-author@example.com")
    learner = await _become_learner(client, db_session, email="peek-learner@example.com")
    group_id = module["translation_group_id"]

    await _open(client, group_id)

    rows = (
        await db_session.execute(
            select(ModuleProgress).where(ModuleProgress.user_id == learner.id)
        )
    ).scalars()
    assert list(rows) == []

    pages = (await _open(client, group_id)).json()["pages"]
    await client.post(f"/api/me/modules/{group_id}/pages/{pages[0]['id']}/view")

    started = (await _open(client, group_id)).json()["progress"]
    assert started["pages_viewed"] == [pages[0]["id"]]


async def test_the_catalog_and_the_viewer_agree_on_the_title(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A rename belongs to the author's draft. Everything a learner is shown —
    the card and the module behind it — names the *published* text."""
    module = await _publish_module(client, db_session, author_email="rename-author@example.com")
    renamed = await client.patch(
        f"/api/content/modules/{module['id']}", json={"title": "Renamed since publishing"}
    )
    assert renamed.status_code == 200

    await _become_learner(client, db_session, email="rename-learner@example.com")
    entry = next(
        row
        for row in (await client.get("/api/catalog/modules")).json()
        if row["translation_group_id"] == module["translation_group_id"]
    )
    opened = (await _open(client, module["translation_group_id"])).json()

    assert entry["title"] == "Phishing Awareness"
    assert opened["title"] == "Phishing Awareness"


async def test_a_learner_reads_the_frozen_version_not_the_authors_draft(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The whole point of publishing: an author revising a live module changes
    nothing a learner sees until they publish again."""
    module = await _publish_module(client, db_session, author_email="draft-author@example.com")
    pages = await client.get(f"/api/content/modules/{module['id']}/pages")
    first_page = pages.json()["pages"][0]
    edited = await client.patch(
        f"/api/content/modules/{module['id']}/pages/{first_page['id']}",
        json={
            "draft_revision": pages.json()["draft_revision"],
            "title": "Rewritten while learners were reading",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Brand new text."),
        },
    )
    assert edited.status_code == 200

    await _become_learner(client, db_session, email="draft-learner@example.com")
    body = (await _open(client, module["translation_group_id"])).json()

    assert [page["title"] for page in body["pages"]] == ["Intro", "Details"]


async def test_a_module_that_is_not_catalog_visible_is_unreachable_by_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Absent from a list is not the same as inaccessible. This is the second one."""
    module = await _publish_module(
        client, db_session, author_email="idor-author@example.com", catalog_visible=False
    )
    await _become_learner(client, db_session, email="idor-learner@example.com")

    response = await _open(client, module["translation_group_id"])

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "module_unavailable"


async def test_an_unknown_translation_group_is_the_same_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """No oracle: "never existed" and "not for you" have to look identical."""
    await _become_learner(client, db_session, email="unknown-learner@example.com")

    response = await _open(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "module_unavailable"


async def test_opening_a_module_without_a_session_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="anon-author@example.com")
    client.cookies.clear()

    assert (await _open(client, module["translation_group_id"])).status_code == 401


async def test_an_author_can_open_a_module_that_is_not_in_the_catalog(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Authors read their own material through the learner's own viewer, which
    is the only way to see what a learner will actually get."""
    module = await _publish_module(
        client, db_session, author_email="preview-author@example.com", catalog_visible=False
    )

    response = await _open(client, module["translation_group_id"])

    assert response.status_code == 200
    assert response.json()["title"] == "Phishing Awareness"


# --- Progress and resuming ------------------------------------------------


async def test_progress_survives_the_session_ending_and_resumes_where_it_stopped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="resume-author@example.com")
    await _become_learner(client, db_session, email="resume-learner@example.com")
    pages = (await _open(client, module["translation_group_id"])).json()["pages"]

    viewed = await client.post(
        f"/api/me/modules/{module['translation_group_id']}/pages/{pages[0]['id']}/view"
    )
    assert viewed.status_code == 200
    assert viewed.json()["current_page_id"] == pages[0]["id"]

    # The learner leaves entirely and comes back later on a new session.
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="resume-learner@example.com")

    resumed = (await _open(client, module["translation_group_id"])).json()

    assert resumed["progress"]["pages_viewed"] == [pages[0]["id"]]
    assert resumed["progress"]["current_page_id"] == pages[0]["id"]


async def test_viewing_the_same_page_twice_records_it_once(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="twice-author@example.com")
    await _become_learner(client, db_session, email="twice-learner@example.com")
    pages = (await _open(client, module["translation_group_id"])).json()["pages"]

    for _ in range(3):
        await client.post(
            f"/api/me/modules/{module['translation_group_id']}/pages/{pages[0]['id']}/view"
        )

    body = (await _open(client, module["translation_group_id"])).json()
    assert body["progress"]["pages_viewed"] == [pages[0]["id"]]


async def test_a_page_id_from_another_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The viewed-pages array is what the attestation is checked against, so
    nothing that is not a page of this version may get into it."""
    module = await _publish_module(client, db_session, author_email="mix-author@example.com")
    other = await _publish_module(
        client, db_session, author_email="mix-author-2@example.com", title="Passwords"
    )
    other_page = (await client.get(f"/api/content/modules/{other['id']}/pages")).json()["pages"][0]
    await _become_learner(client, db_session, email="mix-learner@example.com")

    response = await client.post(
        f"/api/me/modules/{module['translation_group_id']}/pages/{other_page['id']}/view"
    )

    assert response.status_code == 404


async def test_recording_a_view_on_a_module_not_open_to_the_learner_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(
        client, db_session, author_email="viewidor-author@example.com", catalog_visible=False
    )
    page = (await client.get(f"/api/content/modules/{module['id']}/pages")).json()["pages"][0]
    await _become_learner(client, db_session, email="viewidor-learner@example.com")

    response = await client.post(
        f"/api/me/modules/{module['translation_group_id']}/pages/{page['id']}/view"
    )

    assert response.status_code == 404


# --- The attestation ------------------------------------------------------


async def test_the_attestation_is_refused_until_every_page_has_been_viewed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="attest-author@example.com")
    await _become_learner(client, db_session, email="attest-learner@example.com")
    pages = (await _open(client, module["translation_group_id"])).json()["pages"]
    await client.post(
        f"/api/me/modules/{module['translation_group_id']}/pages/{pages[0]['id']}/view"
    )

    response = await client.post(f"/api/me/modules/{module['translation_group_id']}/complete")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pages_outstanding"
    assert response.json()["detail"]["pages_outstanding"] == 1
    assert response.json()["detail"]["pages_total"] == 2


async def test_the_attestation_records_the_version_that_was_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="done-author@example.com")
    await _become_learner(client, db_session, email="done-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await _open(client, group_id)).json()["pages"]
    await _view_every_page(client, group_id, pages)

    response = await client.post(f"/api/me/modules/{group_id}/complete")

    assert response.status_code == 200, response.text
    assert response.json()["completed_at"] is not None
    assert response.json()["completed_version_number"] == 1


async def test_a_completed_module_can_be_reopened(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="reopen-author@example.com")
    await _become_learner(client, db_session, email="reopen-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await _open(client, group_id)).json()["pages"]
    await _view_every_page(client, group_id, pages)
    await client.post(f"/api/me/modules/{group_id}/complete")

    reopened = await _open(client, group_id)

    assert reopened.status_code == 200
    assert reopened.json()["progress"]["completed_at"] is not None


async def test_completing_a_module_not_open_to_the_learner_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(
        client, db_session, author_email="completeidor-author@example.com", catalog_visible=False
    )
    await _become_learner(client, db_session, email="completeidor-learner@example.com")

    response = await client.post(f"/api/me/modules/{module['translation_group_id']}/complete")

    assert response.status_code == 404


# --- The learner's own list -----------------------------------------------


async def test_my_modules_lists_what_the_learner_completed_and_when(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="list-author@example.com")
    await _become_learner(client, db_session, email="list-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await _open(client, group_id)).json()["pages"]
    await _view_every_page(client, group_id, pages)
    await client.post(f"/api/me/modules/{group_id}/complete")

    response = await client.get("/api/me/modules")

    assert response.status_code == 200
    mine = [row for row in response.json() if row["translation_group_id"] == group_id]
    assert len(mine) == 1
    assert mine[0]["title"] == "Phishing Awareness"
    assert mine[0]["completed_at"] is not None
    assert mine[0]["completed_version_number"] == 1
    assert mine[0]["available"] is True


async def test_my_modules_shows_nothing_for_a_learner_who_has_opened_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _become_learner(client, db_session, email="empty-learner@example.com")

    assert (await client.get("/api/me/modules")).json() == []


# --- Withdrawn material ---------------------------------------------------


async def test_a_learner_mid_module_is_told_it_is_gone_and_keeps_their_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="pulled-author@example.com")
    learner = await _become_learner(client, db_session, email="pulled-learner@example.com")
    group_id = module["translation_group_id"]
    pages = (await _open(client, group_id)).json()["pages"]
    await client.post(f"/api/me/modules/{group_id}/pages/{pages[0]['id']}/view")

    # The author pulls it out of circulation while the learner is part-way in.
    await _login(client, email="pulled-author@example.com")
    assert (await client.post(f"/api/content/modules/{module['id']}/unpublish")).status_code == 200

    await _login(client, email="pulled-learner@example.com")
    response = await _open(client, group_id)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "module_unavailable"

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == learner.id,
                ModuleProgress.translation_group_id == uuid.UUID(group_id),
            )
        )
    ).scalar_one()
    assert progress.pages_viewed == [pages[0]["id"]]

    # And it stays on their own list, marked as no longer openable.
    listed = [
        row for row in (await client.get("/api/me/modules")).json()
        if row["translation_group_id"] == group_id
    ]
    assert listed[0]["available"] is False


# --- Assets, the other door into the same material ------------------------


async def test_a_learner_can_fetch_an_asset_of_a_catalog_module(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="assetcat-author@example.com", role_name="Content Manager"
    )
    created = await client.post(
        "/api/content/modules", json={"title": "With an image", "language": "en"}
    )
    module = created.json()
    await client.post(
        f"/api/content/modules/{module['id']}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    await _add_page(client, module["id"], title="Intro", revision=1)
    await client.patch(f"/api/content/modules/{module['id']}", json={"catalog_visible": True})
    await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
    )
    assets = (await client.get(f"/api/content/modules/{module['id']}/assets")).json()["assets"]

    await _become_learner(client, db_session, email="assetcat-learner@example.com")
    response = await client.get(assets[0]["url"], follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["Location"].startswith("https://assets.example.test/")


async def test_a_learner_cannot_fetch_an_asset_of_a_module_not_open_to_them(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The page and the image inside it are one decision, made in one place."""
    await _login_with_role(
        client, db_session, email="assethidden-author@example.com", role_name="Content Manager"
    )
    created = await client.post(
        "/api/content/modules", json={"title": "Private", "language": "en"}
    )
    module = created.json()
    await client.post(
        f"/api/content/modules/{module['id']}/assets",
        data={"kind": "attachment"},
        files={"file": ("policy.pdf", PDF, "application/octet-stream")},
    )
    await _add_page(client, module["id"], title="Intro", revision=1)
    await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
    )
    assets = (await client.get(f"/api/content/modules/{module['id']}/assets")).json()["assets"]

    await _become_learner(client, db_session, email="assethidden-learner@example.com")
    response = await client.get(assets[0]["url"], follow_redirects=False)

    assert response.status_code == 404


async def test_the_viewer_lists_a_modules_attachments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="attach-author@example.com", role_name="Content Manager"
    )
    created = await client.post(
        "/api/content/modules", json={"title": "With a PDF", "language": "en"}
    )
    module = created.json()
    await client.post(
        f"/api/content/modules/{module['id']}/assets",
        data={"kind": "attachment"},
        files={"file": ("policy.pdf", PDF, "application/octet-stream")},
    )
    await client.post(
        f"/api/content/modules/{module['id']}/assets",
        data={"kind": "image"},
        files={"file": ("diagram.png", PNG, "application/octet-stream")},
    )
    await _add_page(client, module["id"], title="Intro", revision=1)
    await client.patch(f"/api/content/modules/{module['id']}", json={"catalog_visible": True})
    published = await client.post(
        f"/api/content/modules/{module['id']}/publish", json={"revision_kind": "minor"}
    )

    await _become_learner(client, db_session, email="attach-learner@example.com")
    body = (await _open(client, published.json()["translation_group_id"])).json()

    # The downloadable file, and only that: an image belongs on the page it is
    # embedded in, not in a list of things to download.
    assert [attachment["original_filename"] for attachment in body["attachments"]] == [
        "policy.pdf"
    ]


# --- Catalog visibility is the author's switch ----------------------------


async def test_an_author_toggles_catalog_visibility_off_again(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="toggle-author@example.com")

    hidden = await client.patch(
        f"/api/content/modules/{module['id']}", json={"catalog_visible": False}
    )

    assert hidden.status_code == 200
    assert hidden.json()["catalog_visible"] is False

    await _become_learner(client, db_session, email="toggle-learner@example.com")
    assert (await _open(client, module["translation_group_id"])).status_code == 404


async def test_toggling_the_catalog_is_not_recorded_as_editing_the_material(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Circulation and authorship are different facts. Putting a module on the
    catalog must not put somebody's name against words they did not write."""
    author = await _login_with_role(
        client, db_session, email="lastedit-author@example.com", role_name="Content Manager"
    )
    created = await client.post(
        "/api/content/modules", json={"title": "Whose words", "language": "en"}
    )
    module = created.json()

    other = await _make_user_with_role(
        db_session, email="lastedit-other@example.com", role_name="Content Manager"
    )
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="lastedit-other@example.com")

    toggled = await client.patch(
        f"/api/content/modules/{module['id']}", json={"catalog_visible": True}
    )

    assert toggled.status_code == 200
    assert toggled.json()["catalog_visible"] is True
    assert toggled.json()["last_edited_by"]["id"] == str(author.id)

    # An edit to the material itself does move it, as it always has.
    edited = await client.patch(
        f"/api/content/modules/{module['id']}", json={"title": "Rewritten"}
    )
    assert edited.json()["last_edited_by"]["id"] == str(other.id)


async def test_an_explicit_null_catalog_visible_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Left out means "leave it alone"; null is a different thing, and it would
    otherwise reach a NOT NULL column."""
    module = await _publish_module(client, db_session, author_email="null-author@example.com")

    response = await client.patch(
        f"/api/content/modules/{module['id']}", json={"catalog_visible": None}
    )

    assert response.status_code == 422


async def test_a_learner_cannot_toggle_catalog_visibility(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await _publish_module(client, db_session, author_email="perm-author@example.com")
    await _become_learner(client, db_session, email="perm-learner@example.com")

    response = await client.patch(
        f"/api/content/modules/{module['id']}", json={"catalog_visible": False}
    )

    assert response.status_code == 403

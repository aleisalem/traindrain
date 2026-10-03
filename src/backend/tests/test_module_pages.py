import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import Module, ModulePage, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(db_session: AsyncSession, *, email: str, role_name: str) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
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


async def _login_as_author(
    client: AsyncClient, db_session: AsyncSession, *, email: str
) -> User:
    author = await _make_user_with_role(db_session, email=email, role_name="Content Manager")
    await _login(client, email=email)
    return author


async def _make_module(client: AsyncClient, *, language: str = "en", title: str = "Module") -> str:
    response = await client.post(
        "/api/content/modules", json={"title": title, "language": language}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _doc(text_content: str = "Hello") -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text_content}]}
        ],
    }


async def _add_page(
    client: AsyncClient, module_id: str, *, title: str, revision: int, body: Any = None
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


# --- Page CRUD ---


async def test_an_author_adds_pages_and_they_come_back_in_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-add@example.com")
    module_id = await _make_module(client)

    first = await _add_page(client, module_id, title="Intro", revision=1)
    assert [page["title"] for page in first["pages"]] == ["Intro"]
    assert first["draft_revision"] == 2

    second = await _add_page(client, module_id, title="Details", revision=2)
    assert [page["title"] for page in second["pages"]] == ["Intro", "Details"]
    assert [page["position"] for page in second["pages"]] == [0, 1]

    listed = await client.get(f"/api/content/modules/{module_id}/pages")
    assert listed.status_code == 200
    assert [page["title"] for page in listed.json()["pages"]] == ["Intro", "Details"]
    assert listed.json()["schema_version"] == SCHEMA_VERSION


async def test_a_page_body_is_stored_as_a_document_tree_not_html(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-json@example.com")
    module_id = await _make_module(client)

    await _add_page(client, module_id, title="Intro", revision=1)

    page = (
        await db_session.execute(
            select(ModulePage).where(ModulePage.module_id == uuid.UUID(module_id))
        )
    ).scalar_one()
    assert isinstance(page.body, dict)
    assert page.body["type"] == "doc"
    assert page.schema_version == SCHEMA_VERSION


async def test_an_author_edits_a_page(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_as_author(client, db_session, email="pages-edit@example.com")
    module_id = await _make_module(client)
    created = await _add_page(client, module_id, title="Intro", revision=1)
    page_id = created["pages"][0]["id"]

    response = await client.patch(
        f"/api/content/modules/{module_id}/pages/{page_id}",
        json={
            "draft_revision": 2,
            "title": "Introduction",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Rewritten"),
        },
    )

    assert response.status_code == 200
    page = response.json()["pages"][0]
    assert page["title"] == "Introduction"
    assert page["body"]["content"][0]["content"][0]["text"] == "Rewritten"


async def test_an_author_edits_only_a_pages_title(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-title@example.com")
    module_id = await _make_module(client)
    created = await _add_page(client, module_id, title="Intro", revision=1)
    page_id = created["pages"][0]["id"]

    response = await client.patch(
        f"/api/content/modules/{module_id}/pages/{page_id}",
        json={"draft_revision": 2, "title": "Introduction"},
    )

    assert response.status_code == 200
    page = response.json()["pages"][0]
    assert page["title"] == "Introduction"
    assert page["body"]["content"][0]["content"][0]["text"] == "Intro"


async def test_an_author_deletes_a_page_and_the_rest_stay_contiguous(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-delete@example.com")
    module_id = await _make_module(client)
    created = await _add_page(client, module_id, title="One", revision=1)
    await _add_page(client, module_id, title="Two", revision=2)
    await _add_page(client, module_id, title="Three", revision=3)
    first_page_id = created["pages"][0]["id"]

    response = await client.request(
        "DELETE",
        f"/api/content/modules/{module_id}/pages/{first_page_id}",
        json={"draft_revision": 4},
    )

    assert response.status_code == 200
    pages = response.json()["pages"]
    assert [page["title"] for page in pages] == ["Two", "Three"]
    assert [page["position"] for page in pages] == [0, 1]


async def test_an_author_reorders_pages(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_as_author(client, db_session, email="pages-reorder@example.com")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="One", revision=1)
    await _add_page(client, module_id, title="Two", revision=2)
    listed = await _add_page(client, module_id, title="Three", revision=3)
    ids = [page["id"] for page in listed["pages"]]

    response = await client.post(
        f"/api/content/modules/{module_id}/pages/reorder",
        json={"draft_revision": 4, "page_ids": [ids[2], ids[0], ids[1]]},
    )

    assert response.status_code == 200
    pages = response.json()["pages"]
    assert [page["title"] for page in pages] == ["Three", "One", "Two"]
    assert [page["position"] for page in pages] == [0, 1, 2]


async def test_a_partial_reorder_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-reorder-partial@example.com")
    module_id = await _make_module(client)
    listed = await _add_page(client, module_id, title="One", revision=1)
    await _add_page(client, module_id, title="Two", revision=2)

    response = await client.post(
        f"/api/content/modules/{module_id}/pages/reorder",
        json={"draft_revision": 3, "page_ids": [listed["pages"][0]["id"]]},
    )

    assert response.status_code == 422


async def test_a_page_from_another_module_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-idor@example.com")
    mine = await _make_module(client, title="Mine")
    theirs = await _make_module(client, title="Theirs")
    created = await _add_page(client, theirs, title="Secret", revision=1)
    page_id = created["pages"][0]["id"]

    response = await client.patch(
        f"/api/content/modules/{mine}/pages/{page_id}",
        json={"draft_revision": 1, "title": "Hijacked"},
    )

    assert response.status_code == 404


# --- The draft's optimistic lock ---


async def test_a_stale_draft_revision_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-conflict@example.com")
    module_id = await _make_module(client)
    # The first author saves, which advances the draft token to 2.
    await _add_page(client, module_id, title="Intro", revision=1)

    # The second author still holds the token they loaded, 1.
    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": 1,
            "title": "Conflicting",
            "schema_version": SCHEMA_VERSION,
            "body": _doc(),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "draft_conflict"
    assert response.json()["detail"]["draft_revision"] == 2

    # And the losing write really did not land.
    listed = await client.get(f"/api/content/modules/{module_id}/pages")
    assert [page["title"] for page in listed.json()["pages"]] == ["Intro"]


async def test_a_successful_write_advances_the_draft_and_records_the_editor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-author@example.com")
    module_id = await _make_module(client)

    editor = await _login_as_author(client, db_session, email="pages-editor@example.com")
    result = await _add_page(client, module_id, title="Intro", revision=1)

    assert result["draft_revision"] == 2
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    await db_session.refresh(module)
    assert module.draft_revision == 2
    assert module.last_edited_by == editor.id


@pytest.mark.parametrize("path_suffix", ["", "/reorder"])
async def test_a_rejected_body_does_not_advance_the_draft(
    client: AsyncClient, db_session: AsyncSession, path_suffix: str
) -> None:
    await _login_as_author(client, db_session, email=f"pages-norev{path_suffix}@example.com")
    module_id = await _make_module(client)

    if path_suffix == "":
        response = await client.post(
            f"/api/content/modules/{module_id}/pages",
            json={
                "draft_revision": 1,
                "title": "Bad",
                "schema_version": SCHEMA_VERSION,
                "body": {"type": "doc", "content": [{"type": "script"}]},
            },
        )
    else:
        response = await client.post(
            f"/api/content/modules/{module_id}/pages/reorder",
            json={"draft_revision": 1, "page_ids": [str(uuid.uuid4())]},
        )

    assert response.status_code == 422
    listed = await client.get(f"/api/content/modules/{module_id}/pages")
    assert listed.json()["draft_revision"] == 1


# --- Adversarial documents: 422, never a silent strip ---


def _page_payload(body: Any, schema_version: int = SCHEMA_VERSION) -> dict[str, Any]:
    return {
        "draft_revision": 1,
        "title": "Hostile",
        "schema_version": schema_version,
        "body": body,
    }


HOSTILE_BODIES: list[tuple[str, Any]] = [
    (
        "unknown_node_type",
        {"type": "doc", "content": [{"type": "script", "content": []}]},
    ),
    (
        "unknown_attribute",
        {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 2, "onclick": "x()"}, "content": []}
            ],
        },
    ),
    (
        "unknown_mark_type",
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "x", "marks": [{"type": "onerror"}]}],
                }
            ],
        },
    ),
    (
        "bad_href",
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "x",
                            "marks": [
                                {"type": "link", "attrs": {"href": "javascript:alert(1)"}}
                            ],
                        }
                    ],
                }
            ],
        },
    ),
    (
        "bad_href",
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "x",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {"href": "data:text/html,<script>alert(1)</script>"},
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    ),
    (
        "bad_href",
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "x",
                            "marks": [
                                {"type": "link", "attrs": {"href": "vbscript:msgbox(1)"}}
                            ],
                        }
                    ],
                }
            ],
        },
    ),
    (
        "bad_src",
        {"type": "doc", "content": [{"type": "image", "attrs": {"src": "javascript:alert(1)"}}]},
    ),
    (
        "bad_src",
        {
            "type": "doc",
            "content": [
                {
                    "type": "image",
                    "attrs": {"src": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="},
                }
            ],
        },
    ),
    (
        "bad_src",
        {
            "type": "doc",
            "content": [{"type": "image", "attrs": {"src": "vbscript:msgbox(1)"}}],
        },
    ),
]


@pytest.mark.parametrize(
    ("expected_code", "body"), HOSTILE_BODIES, ids=[f"{i}-{c}" for i, (c, _) in enumerate(HOSTILE_BODIES)]
)
async def test_a_hostile_document_is_rejected_and_nothing_is_stored(
    client: AsyncClient, db_session: AsyncSession, expected_code: str, body: Any
) -> None:
    await _login_as_author(client, db_session, email=f"hostile-{hash(str(body))}@example.com")
    module_id = await _make_module(client)

    response = await client.post(
        f"/api/content/modules/{module_id}/pages", json=_page_payload(body)
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == expected_code
    # Not stripped and accepted — no page row exists at all.
    listed = await client.get(f"/api/content/modules/{module_id}/pages")
    assert listed.json()["pages"] == []


async def test_an_over_deep_document_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="hostile-deep@example.com")
    module_id = await _make_module(client)
    node: dict[str, Any] = {"type": "paragraph", "content": []}
    for _ in range(40):
        node = {"type": "blockquote", "content": [node]}

    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json=_page_payload({"type": "doc", "content": [node]}),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "too_deep"


async def test_an_over_large_document_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="hostile-large@example.com")
    module_id = await _make_module(client)

    response = await client.post(
        f"/api/content/modules/{module_id}/pages", json=_page_payload(_doc("x" * 300_000))
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "document_too_large"


async def test_a_mismatched_schema_version_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="hostile-version@example.com")
    module_id = await _make_module(client)

    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json=_page_payload(_doc(), schema_version=SCHEMA_VERSION + 1),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "schema_version_mismatch"


# --- Search text ---


async def test_search_text_holds_the_prose_and_the_index_stems_it_by_module_language(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-search@example.com")
    module_id = await _make_module(client, language="de", title="Brandschutz")

    await _add_page(
        client,
        module_id,
        title="Regeln",
        revision=1,
        body=_doc("Die Feuerschutzregeln gelten für alle"),
    )

    page = (
        await db_session.execute(
            select(ModulePage).where(ModulePage.module_id == uuid.UUID(module_id))
        )
    ).scalar_one()
    assert page.search_text == "Die Feuerschutzregeln gelten für alle"
    assert page.search_config == "german"

    # The generated tsvector column carries German stemming: "gelten" stems to
    # "gelt", which English rules would never produce.
    tsv = (
        await db_session.execute(
            text("select search_tsv::text from module_pages where id = :id"),
            {"id": page.id},
        )
    ).scalar_one()
    assert "'gelt'" in tsv
    # And nothing from the tree's structure or a URL leaked into the index.
    assert "paragraph" not in tsv


async def test_an_english_module_is_indexed_with_english_stemming(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_author(client, db_session, email="pages-search-en@example.com")
    module_id = await _make_module(client, language="en")

    await _add_page(client, module_id, title="Rules", revision=1, body=_doc("Fire safety rules"))

    page = (
        await db_session.execute(
            select(ModulePage).where(ModulePage.module_id == uuid.UUID(module_id))
        )
    ).scalar_one()
    assert page.search_config == "english"
    tsv = (
        await db_session.execute(
            text("select search_tsv::text from module_pages where id = :id"),
            {"id": page.id},
        )
    ).scalar_one()
    assert "'safeti'" in tsv


# --- Authorization ---


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "/pages"),
        ("POST", "/pages"),
        ("POST", "/pages/reorder"),
        ("PATCH", f"/pages/{uuid.uuid4()}"),
        ("DELETE", f"/pages/{uuid.uuid4()}"),
    ],
)
async def test_a_learner_is_forbidden_from_every_page_route(
    client: AsyncClient, db_session: AsyncSession, method: str, suffix: str
) -> None:
    await _make_user_with_role(
        db_session, email=f"learner-page-{hash(suffix + method)}@example.com", role_name="Learner"
    )
    await _login(client, email=f"learner-page-{hash(suffix + method)}@example.com")

    response = await client.request(
        method,
        f"/api/content/modules/{uuid.uuid4()}{suffix}",
        json={"draft_revision": 1, "page_ids": [str(uuid.uuid4())]},
    )

    assert response.status_code == 403

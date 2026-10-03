"""Ticket 10: search, filters, and tags.

Two things this file holds down. First, tags: normalized and deduplicated at
write time, so "Phishing" and "phishing" are one tag rather than two that
happen to look alike, and the same normalization narrows a filter query.
Second, search: title/description matching is stemmed under the config each
module's own `language` selects — never guessed from the query text — which is
what lets a German module be found by a German plural while the identical
English text is not.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

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


async def _become(client: AsyncClient, db_session: AsyncSession, *, email: str, role_name: str) -> User:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db_session, email=email, role_name=role_name)


def _doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def _create_module(
    client: AsyncClient,
    *,
    title: str,
    description: str | None = None,
    language: str = "en",
) -> dict[str, Any]:
    """Create a module under whichever session is already logged in.

    Deliberately doesn't log in itself: a test creating several modules to
    filter over needs them all made by the same author session, and logging in
    again for each would try to create a second user under the same email.
    """
    response = await client.post(
        "/api/content/modules",
        json={"title": title, "description": description, "language": language},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _patch(client: AsyncClient, module_id: str, **fields: Any) -> dict[str, Any]:
    response = await client.patch(f"/api/content/modules/{module_id}", json=fields)
    assert response.status_code == 200, response.text
    return response.json()


async def _publish(client: AsyncClient, module_id: str) -> dict[str, Any]:
    add_page = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": 1,
            "title": "Intro",
            "schema_version": SCHEMA_VERSION,
            "body": _doc("Some text."),
        },
    )
    assert add_page.status_code == 201, add_page.text
    published = await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": "minor"}
    )
    assert published.status_code == 200, published.text
    return published.json()


# --- Tags: normalization, dedup, and the autocomplete list -----------------


async def test_patching_tags_normalizes_and_dedupes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tags-norm@example.com", role_name="Content Manager"
    )
    module = await _create_module(client, title="Phishing Awareness")

    updated = await _patch(
        client, module["id"], tags=["Phishing", " phishing ", "Security", "PHISHING"]
    )

    assert updated["tags"] == ["phishing", "security"]


async def test_setting_tags_to_an_empty_list_clears_them(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tags-clear@example.com", role_name="Content Manager"
    )
    module = await _create_module(client, title="Fire Safety")
    await _patch(client, module["id"], tags=["safety"])

    cleared = await _patch(client, module["id"], tags=[])

    assert cleared["tags"] == []


async def test_leaving_tags_out_of_a_patch_leaves_them_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tags-untouched@example.com", role_name="Content Manager"
    )
    module = await _create_module(client, title="Fire Safety")
    await _patch(client, module["id"], tags=["safety"])

    updated = await _patch(client, module["id"], title="Fire Safety (updated)")

    assert updated["tags"] == ["safety"]


async def test_a_tag_over_the_length_cap_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tags-too-long@example.com", role_name="Content Manager"
    )
    module = await _create_module(client, title="Fire Safety")

    response = await client.patch(
        f"/api/content/modules/{module['id']}", json={"tags": ["x" * 51]}
    )

    assert response.status_code == 422


async def test_more_than_the_tag_cap_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tags-too-many@example.com", role_name="Content Manager"
    )
    module = await _create_module(client, title="Fire Safety")

    response = await client.patch(
        f"/api/content/modules/{module['id']}", json={"tags": [f"tag-{i}" for i in range(21)]}
    )

    assert response.status_code == 422


async def test_the_tag_list_is_every_tag_currently_in_use(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tags-list@example.com", role_name="Content Manager"
    )
    first = await _create_module(client, title="Phishing Awareness")
    await _patch(client, first["id"], tags=["phishing", "security"])
    second = await _create_module(client, title="Fire Safety")
    await _patch(client, second["id"], tags=["safety", "security"])

    response = await client.get("/api/content/tags")

    assert response.status_code == 200
    assert response.json() == ["phishing", "safety", "security"]


async def test_a_learner_gets_403_from_the_tag_autocomplete(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _become(client, db_session, email="tags-learner@example.com", role_name="Learner")

    response = await client.get("/api/content/tags")

    assert response.status_code == 403


# --- The authoring module list: search and filters --------------------------


async def test_module_list_search_matches_title_and_description(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="search-1@example.com", role_name="Content Manager"
    )
    await _create_module(
        client, title="Phishing Awareness", description="How to spot a phish."
    )
    await _create_module(client, title="Fire Safety", description="What to do in a fire.")

    response = await client.get("/api/content/modules", params={"q": "phishing"})

    assert response.status_code == 200
    titles = [module["title"] for module in response.json()]
    assert titles == ["Phishing Awareness"]


async def test_german_language_content_is_matched_with_german_stemming(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="search-de@example.com", role_name="Content Manager"
    )
    text = "Diese Schulung behandelt Passwortsicherheit."
    german = await _create_module(
        client, title="Passwortschulung", description=text, language="de"
    )
    english = await _create_module(
        client, title="Password Course", description=text, language="en"
    )

    # "Schulungen" is the German plural of the "Schulung" in both descriptions
    # — only the row whose own language selects the German stemmer should
    # match it, proving the configuration comes from the module, not a guess
    # at what the query is written in.
    response = await client.get("/api/content/modules", params={"q": "Schulungen"})

    assert response.status_code == 200
    ids = {module["id"] for module in response.json()}
    assert german["id"] in ids
    assert english["id"] not in ids


async def test_module_list_filters_combine(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="filters@example.com", role_name="Content Manager"
    )
    draft_en_tagged = await _create_module(client, title="Draft EN Tagged")
    await _patch(client, draft_en_tagged["id"], tags=["security"])

    published_en_tagged = await _create_module(client, title="Published EN Tagged")
    await _patch(client, published_en_tagged["id"], tags=["security"])
    await _publish(client, published_en_tagged["id"])

    published_en_untagged = await _create_module(client, title="Published EN Untagged")
    await _publish(client, published_en_untagged["id"])

    published_de_tagged = await _create_module(
        client, title="Published DE Tagged", language="de"
    )
    await _patch(client, published_de_tagged["id"], tags=["security"])
    await _publish(client, published_de_tagged["id"])

    response = await client.get(
        "/api/content/modules",
        params={"language": "en", "status": "published", "tags": ["security"]},
    )

    assert response.status_code == 200
    titles = [module["title"] for module in response.json()]
    assert titles == ["Published EN Tagged"]


async def test_module_list_tag_filter_requires_every_requested_tag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="tag-and@example.com", role_name="Content Manager"
    )
    both = await _create_module(client, title="Both Tags")
    await _patch(client, both["id"], tags=["security", "phishing"])
    one = await _create_module(client, title="One Tag")
    await _patch(client, one["id"], tags=["security"])

    response = await client.get(
        "/api/content/modules", params={"tags": ["security", "phishing"]}
    )

    assert response.status_code == 200
    titles = [module["title"] for module in response.json()]
    assert titles == ["Both Tags"]


# --- The learner catalog: search and filters --------------------------------


async def test_catalog_search_never_returns_a_module_that_is_not_catalog_visible_and_published(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="catalog-search@example.com", role_name="Content Manager"
    )
    eligible = await _create_module(
        client, title="Phishing Awareness", description="Spot the phish."
    )
    await _patch(client, eligible["id"], tags=["security"], catalog_visible=True)
    await _publish(client, eligible["id"])

    not_catalog_visible = await _create_module(
        client, title="Phishing Backstage", description="Spot the phish."
    )
    await _patch(client, not_catalog_visible["id"], tags=["security"])
    await _publish(client, not_catalog_visible["id"])

    still_draft = await _create_module(
        client, title="Phishing In Progress", description="Spot the phish."
    )
    await _patch(client, still_draft["id"], tags=["security"], catalog_visible=True)

    await _become(client, db_session, email="catalog-search-learner@example.com", role_name="Learner")

    response = await client.get(
        "/api/catalog/modules", params={"q": "phish", "tags": ["security"]}
    )

    assert response.status_code == 200
    titles = [entry["title"] for entry in response.json()]
    assert titles == ["Phishing Awareness"]


async def test_catalog_filters_combine_by_language_and_tag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="catalog-filters@example.com", role_name="Content Manager"
    )
    en_match = await _create_module(client, title="EN Match")
    await _patch(client, en_match["id"], tags=["security"], catalog_visible=True)
    await _publish(client, en_match["id"])

    en_other_tag = await _create_module(client, title="EN Other Tag")
    await _patch(client, en_other_tag["id"], tags=["safety"], catalog_visible=True)
    await _publish(client, en_other_tag["id"])

    de_match = await _create_module(client, title="DE Match", language="de")
    await _patch(client, de_match["id"], tags=["security"], catalog_visible=True)
    await _publish(client, de_match["id"])

    await _become(client, db_session, email="catalog-filters-learner@example.com", role_name="Learner")

    response = await client.get(
        "/api/catalog/modules", params={"language": "en", "tags": ["security"]}
    )

    assert response.status_code == 200
    titles = [entry["title"] for entry in response.json()]
    assert titles == ["EN Match"]

"""Translations: linking variants, nominating a primary, and language resolution.

Two things this file holds down. First, that a translation group stays a
coherent unit: linking a module in is refused wherever it would orphan
something (a module's own siblings, or learner history already recorded
against it), and the unique-language constraint holds end to end. Second, that
a learner's variant resolution is a single, stable choice — their language,
falling back to the primary, falling back to anything — that keeps naming the
same text across requests unless they explicitly ask to switch, and that a
switch resets what has to be reset without touching what must not be.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import AuditLog, Module, ModuleProgress, ModuleTranslationGroup, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(
    db_session: AsyncSession,
    *,
    email: str,
    role_name: str,
    preferred_language: str | None = None,
) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Cora",
        last_name="Manager",
        preferred_language=preferred_language,
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
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    email: str,
    role_name: str,
    preferred_language: str | None = None,
) -> User:
    user = await _make_user_with_role(
        db_session, email=email, role_name=role_name, preferred_language=preferred_language
    )
    await _login(client, email=email)
    return user


async def _become(
    client: AsyncClient, db_session: AsyncSession, *, email: str, role_name: str, **kwargs: Any
) -> User:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db_session, email=email, role_name=role_name, **kwargs)


def _doc(text_content: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text_content}]}],
    }


async def _make_module(
    client: AsyncClient, *, title: str, language: str = "en"
) -> dict[str, Any]:
    response = await client.post(
        "/api/content/modules",
        json={"title": title, "description": "Material.", "language": language},
    )
    assert response.status_code == 201, response.text
    return response.json()


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


async def _publish(
    client: AsyncClient, module_id: str, *, catalog_visible: bool = True
) -> dict[str, Any]:
    if catalog_visible:
        patched = await client.patch(
            f"/api/content/modules/{module_id}", json={"catalog_visible": True}
        )
        assert patched.status_code == 200
    response = await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": "minor"}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _make_published_module(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    title: str,
    author_email: str,
    language: str = "en",
    catalog_visible: bool = True,
) -> dict[str, Any]:
    await _login_with_role(client, db_session, email=author_email, role_name="Content Manager")
    module = await _make_module(client, title=title, language=language)
    await _add_page(client, module["id"], title="Intro", revision=1)
    return await _publish(client, module["id"], catalog_visible=catalog_visible)


# --- Linking a variant ------------------------------------------------------


async def test_a_content_manager_links_a_standalone_module_as_a_variant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client, db_session, email="link-author@example.com", role_name="Content Manager"
    )
    en_module = await _make_module(client, title="Phishing Awareness", language="en")
    de_module = await _make_module(client, title="Phishing-Bewusstsein", language="de")

    response = await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == en_module["translation_group_id"]
    languages = {variant["language"] for variant in body["variants"]}
    assert languages == {"en", "de"}
    # The primary is untouched by linking — nominating one is a separate act.
    assert body["primary_module_id"] == en_module["id"]

    moved = await db_session.get(Module, uuid.UUID(de_module["id"]))
    assert str(moved.translation_group_id) == en_module["translation_group_id"]

    # The German module's own auto-created group is gone — it held nothing else.
    old_group = await db_session.get(
        ModuleTranslationGroup, uuid.UUID(de_module["translation_group_id"])
    )
    assert old_group is None

    audit_entry = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "translation_variant_linked")
        )
    ).scalar_one()
    assert audit_entry.actor_user_id == author.id
    assert audit_entry.detail["module_id"] == de_module["id"]
    assert audit_entry.detail["translation_group_id"] == en_module["translation_group_id"]


async def test_the_unique_language_constraint_is_enforced_on_link(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="dupe-lang@example.com", role_name="Content Manager"
    )
    en_module = await _make_module(client, title="Original", language="en")
    other_en_module = await _make_module(client, title="Also English", language="en")

    response = await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": other_en_module["id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "language_already_exists"


async def test_linking_a_module_that_already_has_translation_siblings_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="siblings@example.com", role_name="Content Manager"
    )
    group_a_en = await _make_module(client, title="A (en)", language="en")
    group_a_de = await _make_module(client, title="A (de)", language="de")
    await client.post(
        f"/api/content/translation-groups/{group_a_en['translation_group_id']}/variants",
        json={"module_id": group_a_de["id"]},
    )
    group_b_en = await _make_module(client, title="B (en)", language="en")

    # group_a_de is no longer standalone — it has an English sibling now.
    response = await client.post(
        f"/api/content/translation-groups/{group_b_en['translation_group_id']}/variants",
        json={"module_id": group_a_de["id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_not_standalone"


async def test_linking_a_module_with_existing_learner_progress_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    published = await _make_published_module(
        client, db_session, title="Already Read", author_email="already-read-author@example.com"
    )
    await _become(
        client, db_session, email="progress-learner@example.com", role_name="Learner"
    )
    opened = await client.get(f"/api/me/modules/{published['translation_group_id']}")
    page_id = opened.json()["pages"][0]["id"]
    await client.post(
        f"/api/me/modules/{published['translation_group_id']}/pages/{page_id}/view"
    )

    await _become(
        client, db_session, email="progress-author@example.com", role_name="Content Manager"
    )
    other = await _make_module(client, title="Other language", language="de")

    response = await client.post(
        f"/api/content/translation-groups/{other['translation_group_id']}/variants",
        json={"module_id": published["id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_has_progress"


async def test_linking_an_unknown_module_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="unknown-module@example.com", role_name="Content Manager"
    )
    group = await _make_module(client, title="Group", language="en")

    response = await client.post(
        f"/api/content/translation-groups/{group['translation_group_id']}/variants",
        json={"module_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


async def test_linking_into_an_unknown_group_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="unknown-group@example.com", role_name="Content Manager"
    )
    module = await _make_module(client, title="Standalone", language="en")

    response = await client.post(
        f"/api/content/translation-groups/{uuid.uuid4()}/variants",
        json={"module_id": module["id"]},
    )

    assert response.status_code == 404


async def test_a_learner_cannot_link_variants(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="link-perm-author@example.com", role_name="Content Manager"
    )
    en_module = await _make_module(client, title="A", language="en")
    de_module = await _make_module(client, title="B", language="de")

    await _become(client, db_session, email="link-perm-learner@example.com", role_name="Learner")
    response = await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )

    assert response.status_code == 403


# --- Nominating a primary ---------------------------------------------------


async def test_setting_the_primary_variant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client, db_session, email="primary-author@example.com", role_name="Content Manager"
    )
    en_module = await _make_module(client, title="Primary test (en)", language="en")
    de_module = await _make_module(client, title="Primary test (de)", language="de")
    await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )

    response = await client.patch(
        f"/api/content/translation-groups/{en_module['translation_group_id']}",
        json={"primary_module_id": de_module["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["primary_module_id"] == de_module["id"]

    group = await db_session.get(
        ModuleTranslationGroup, uuid.UUID(en_module["translation_group_id"])
    )
    assert str(group.primary_module_id) == de_module["id"]

    audit_entry = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "translation_primary_changed")
        )
    ).scalar_one()
    assert audit_entry.actor_user_id == author.id


async def test_setting_a_primary_that_is_not_a_variant_of_the_group_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="wrong-group@example.com", role_name="Content Manager"
    )
    group = await _make_module(client, title="Group", language="en")
    outsider = await _make_module(client, title="Outsider", language="de")

    response = await client.patch(
        f"/api/content/translation-groups/{group['translation_group_id']}",
        json={"primary_module_id": outsider["id"]},
    )

    assert response.status_code == 404


async def test_getting_a_translation_group_lists_its_variants(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="get-group@example.com", role_name="Content Manager"
    )
    en_module = await _make_module(client, title="Get group (en)", language="en")
    de_module = await _make_module(client, title="Get group (de)", language="de")
    await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )

    response = await client.get(
        f"/api/content/translation-groups/{en_module['translation_group_id']}"
    )

    assert response.status_code == 200
    languages = sorted(variant["language"] for variant in response.json()["variants"])
    assert languages == ["de", "en"]


# --- Independent publishing --------------------------------------------------


async def test_each_variant_publishes_independently(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="indep-author@example.com", role_name="Content Manager"
    )
    en_module = await _make_module(client, title="Independent (en)", language="en")
    de_module = await _make_module(client, title="Independent (de)", language="de")
    await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )
    await _add_page(client, en_module["id"], title="Intro", revision=1)
    await _add_page(client, de_module["id"], title="Einleitung", revision=1)

    published_en = await _publish(client, en_module["id"])
    assert published_en["current_version_number"] == 1

    de_unpublished_status = (await client.get(f"/api/content/modules/{de_module['id']}")).json()
    assert de_unpublished_status["status"] == "draft"
    assert de_unpublished_status["current_version_number"] is None

    published_de = await _publish(client, de_module["id"])
    assert published_de["current_version_number"] == 1

    # A second publish of the English variant does not touch the German one.
    re_en = await client.post(
        f"/api/content/modules/{en_module['id']}/publish", json={"revision_kind": "minor"}
    )
    assert re_en.json()["current_version_number"] == 2
    de_after = (await client.get(f"/api/content/modules/{de_module['id']}")).json()
    assert de_after["current_version_number"] == 1


# --- Learner-side language resolution ---------------------------------------


async def _make_bilingual_group(
    client: AsyncClient, *, title_en: str = "Bilingual", title_de: str = "Zweisprachig"
) -> tuple[dict[str, Any], dict[str, Any]]:
    en_module = await _make_module(client, title=title_en, language="en")
    de_module = await _make_module(client, title=title_de, language="de")
    await client.post(
        f"/api/content/translation-groups/{en_module['translation_group_id']}/variants",
        json={"module_id": de_module["id"]},
    )
    await _add_page(client, en_module["id"], title="Intro", revision=1)
    await _add_page(client, de_module["id"], title="Einleitung", revision=1)
    published_en = await _publish(client, en_module["id"])
    published_de = await _publish(client, de_module["id"])
    return published_en, published_de


async def test_a_learner_gets_the_variant_matching_their_preferred_language(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="resolve-de-author@example.com", role_name="Content Manager"
    )
    published_en, published_de = await _make_bilingual_group(
        client, title_en="Resolve DE (en)", title_de="Resolve DE (de)"
    )

    await _become(
        client,
        db_session,
        email="resolve-de-learner@example.com",
        role_name="Learner",
        preferred_language="de",
    )

    response = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")

    assert response.status_code == 200
    assert response.json()["language"] == "de"
    assert response.json()["module_id"] == published_de["id"]
    assert sorted(response.json()["available_languages"]) == ["de", "en"]


async def test_a_learner_whose_language_has_no_variant_gets_the_primary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="resolve-primary-author@example.com", role_name="Content Manager"
    )
    published_en, _ = await _make_bilingual_group(
        client, title_en="Resolve Primary (en)", title_de="Resolve Primary (de)"
    )
    # English is the primary: it was the group's original module.

    await _become(
        client,
        db_session,
        email="resolve-primary-learner@example.com",
        role_name="Learner",
        preferred_language="fr",
    )

    response = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")

    assert response.status_code == 200
    assert response.json()["module_id"] == published_en["id"]


async def test_a_learner_with_no_matching_preference_or_primary_gets_any_published_variant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The third branch: neither the learner's language nor the primary is on
    offer, so whatever is left is used — deterministically, so two requests
    with nothing to prefer still agree."""
    await _login_with_role(
        client, db_session, email="resolve-any-author@example.com", role_name="Content Manager"
    )
    published_en, published_de = await _make_bilingual_group(
        client, title_en="Resolve Any (en)", title_de="Resolve Any (de)"
    )
    # The primary (English) goes out of circulation, so it is no longer a
    # candidate at all — only the fallback-of-last-resort branch is left.
    await client.post(f"/api/content/modules/{published_en['id']}/unpublish")

    await _become(
        client,
        db_session,
        email="resolve-any-learner@example.com",
        role_name="Learner",
        preferred_language="fr",
    )

    first = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")
    second = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")

    assert first.status_code == 200
    assert first.json()["module_id"] == published_de["id"]
    assert first.json()["module_id"] == second.json()["module_id"]


async def test_the_variant_actually_read_is_recorded_on_the_progress_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="record-author@example.com", role_name="Content Manager"
    )
    published_en, published_de = await _make_bilingual_group(
        client, title_en="Record (en)", title_de="Record (de)"
    )

    learner = await _become(
        client,
        db_session,
        email="record-learner@example.com",
        role_name="Learner",
        preferred_language="de",
    )
    opened = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")
    page_id = opened.json()["pages"][0]["id"]
    await client.post(
        f"/api/me/modules/{published_en['translation_group_id']}/pages/{page_id}/view"
    )

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(ModuleProgress.user_id == learner.id)
        )
    ).scalar_one()
    assert str(progress.module_id) == published_de["id"]


async def test_the_variant_stays_stable_across_requests_even_if_preference_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Once a learner has read pages of one text, resolution must not silently
    move them to another — the pages they viewed only mean something within the
    variant they were viewed in."""
    await _login_with_role(
        client, db_session, email="stable-author@example.com", role_name="Content Manager"
    )
    published_en, _ = await _make_bilingual_group(
        client, title_en="Stable (en)", title_de="Stable (de)"
    )

    learner = await _become(
        client,
        db_session,
        email="stable-learner@example.com",
        role_name="Learner",
        preferred_language="en",
    )
    opened = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")
    assert opened.json()["module_id"] == published_en["id"]
    page_id = opened.json()["pages"][0]["id"]
    await client.post(
        f"/api/me/modules/{published_en['translation_group_id']}/pages/{page_id}/view"
    )

    # Their profile language changes after the fact.
    learner.preferred_language = "de"
    db_session.add(learner)
    await db_session.commit()

    reopened = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")

    assert reopened.json()["module_id"] == published_en["id"]


async def test_the_catalog_shows_the_variant_the_learner_is_actually_reading(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="catalog-stable-author@example.com", role_name="Content Manager"
    )
    published_en, _ = await _make_bilingual_group(
        client, title_en="Catalog Stable (en)", title_de="Catalog Stable (de)"
    )

    await _become(
        client,
        db_session,
        email="catalog-stable-learner@example.com",
        role_name="Learner",
        preferred_language="de",
    )
    await client.get(f"/api/me/modules/{published_en['translation_group_id']}")
    page = (
        await client.get(f"/api/me/modules/{published_en['translation_group_id']}")
    ).json()["pages"][0]
    await client.post(
        f"/api/me/modules/{published_en['translation_group_id']}/pages/{page['id']}/view"
    )

    entry = next(
        row
        for row in (await client.get("/api/catalog/modules")).json()
        if row["translation_group_id"] == published_en["translation_group_id"]
    )
    assert entry["language"] == "de"


# --- Explicit language switch -------------------------------------------------


async def test_a_learner_can_switch_language_explicitly(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="switch-author@example.com", role_name="Content Manager"
    )
    published_en, published_de = await _make_bilingual_group(
        client, title_en="Switch (en)", title_de="Switch (de)"
    )

    learner = await _become(
        client, db_session, email="switch-learner@example.com", role_name="Learner"
    )
    opened = await client.get(f"/api/me/modules/{published_en['translation_group_id']}")
    en_page = opened.json()["pages"][0]
    await client.post(
        f"/api/me/modules/{published_en['translation_group_id']}/pages/{en_page['id']}/view"
    )

    switched = await client.post(
        f"/api/me/modules/{published_en['translation_group_id']}/language",
        json={"language": "de"},
    )

    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["module_id"] == published_de["id"]
    assert body["language"] == "de"
    # Pages are different rows in a different text, so the record of which ones
    # were seen resets — the German intro has not been read yet.
    assert body["progress"]["pages_viewed"] == []

    progress = (
        await db_session.execute(
            select(ModuleProgress).where(ModuleProgress.user_id == learner.id)
        )
    ).scalar_one()
    assert str(progress.module_id) == published_de["id"]
    assert progress.pages_viewed == []


async def test_switching_language_preserves_started_at_and_a_prior_completion(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="switch-complete-author@example.com", role_name="Content Manager"
    )
    published_en, published_de = await _make_bilingual_group(
        client, title_en="Switch Complete (en)", title_de="Switch Complete (de)"
    )

    await _become(
        client, db_session, email="switch-complete-learner@example.com", role_name="Learner"
    )
    group_id = published_en["translation_group_id"]
    opened = await client.get(f"/api/me/modules/{group_id}")
    en_page = opened.json()["pages"][0]
    await client.post(f"/api/me/modules/{group_id}/pages/{en_page['id']}/view")
    completed = await client.post(f"/api/me/modules/{group_id}/complete")
    assert completed.status_code == 200
    started_at_value = completed.json()["started_at"]
    completed_at_value = completed.json()["completed_at"]

    switched = await client.post(
        f"/api/me/modules/{group_id}/language", json={"language": "de"}
    )

    assert switched.status_code == 200, switched.text
    assert switched.json()["module_id"] == published_de["id"]
    progress = switched.json()["progress"]
    assert progress["started_at"] == started_at_value
    assert progress["completed_at"] == completed_at_value
    # `completed_version_number` (1) is English's own numbering — it must stay
    # paired with the English module, not silently reattributed to German just
    # because `module_id` moved on to it.
    assert progress["completed_module_id"] == published_en["id"]
    assert progress["completed_version_number"] == 1
    assert progress["pages_viewed"] == []


async def test_my_learning_shows_the_completed_variants_own_title_after_a_switch(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`title`/`language` shown for a completed row have to describe the same
    variant `completed_version_number` was attested against — never whichever
    variant a later, unrelated switch happens to leave `module_id` pointing
    at, which would pair the English module's version number with the German
    module's name."""
    await _login_with_role(
        client, db_session, email="mine-switch-author@example.com", role_name="Content Manager"
    )
    published_en, _ = await _make_bilingual_group(
        client, title_en="Mine Switch (en)", title_de="Mine Switch (de)"
    )

    await _become(
        client, db_session, email="mine-switch-learner@example.com", role_name="Learner"
    )
    group_id = published_en["translation_group_id"]
    en_page = (await client.get(f"/api/me/modules/{group_id}")).json()["pages"][0]
    await client.post(f"/api/me/modules/{group_id}/pages/{en_page['id']}/view")
    await client.post(f"/api/me/modules/{group_id}/complete")

    await client.post(f"/api/me/modules/{group_id}/language", json={"language": "de"})

    mine = next(
        row
        for row in (await client.get("/api/me/modules")).json()
        if row["translation_group_id"] == group_id
    )
    assert mine["title"] == published_en["title"]
    assert mine["language"] == "en"
    assert mine["completed_version_number"] == 1


async def test_switching_to_an_unavailable_language_is_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    published = await _make_published_module(
        client, db_session, title="Only English", author_email="only-en-author@example.com"
    )
    await _become(
        client, db_session, email="switch-missing-learner@example.com", role_name="Learner"
    )
    await client.get(f"/api/me/modules/{published['translation_group_id']}")

    response = await client.post(
        f"/api/me/modules/{published['translation_group_id']}/language",
        json={"language": "de"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "variant_unavailable"


async def test_switching_language_without_a_session_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    published = await _make_published_module(
        client, db_session, title="Anon switch", author_email="anon-switch-author@example.com"
    )
    client.cookies.clear()

    response = await client.post(
        f"/api/me/modules/{published['translation_group_id']}/language",
        json={"language": "en"},
    )

    assert response.status_code == 401

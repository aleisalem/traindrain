"""Quizzes across translations, duplicate, export and import (Release 2, ticket 10).

A quiz belongs to a module row, so variants author theirs independently; what
must agree across a group is only whether one exists. Duplicate and export carry
the draft quiz, and import holds an archive's quiz to the validators authoring
uses.
"""

import json
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import AuditLog
from tests.test_module_publishing import _login_with_role
from tests.test_module_transfer import (
    _build_zip,
    _export,
    _import,
    _minimal_manifest,
    _read_manifest,
)
from tests.test_quiz_authoring import _add_question, _create_quiz, _option, _question
from tests.test_translations import _make_module


async def _author(client: AsyncClient, db_session: AsyncSession, email: str) -> None:
    await _login_with_role(client, db_session, email=email, role_name="Content Manager")


async def _quiz_for(client: AsyncClient, module_id: str, **settings: Any) -> None:
    assert (await _create_quiz(client, module_id, **settings)).status_code == 200
    response = await _add_question(client, module_id, _question())
    assert response.status_code == 201, response.text


async def _link(client: AsyncClient, group_id: str, module_id: str) -> Any:
    return await client.post(
        f"/api/content/translation-groups/{group_id}/variants", json={"module_id": module_id}
    )


async def _pair(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    en = await _make_module(client, title="Phishing", language="en")
    de = await _make_module(client, title="Phishing DE", language="de")
    return en, de


# --- Linking ----------------------------------------------------------------


async def test_linking_is_refused_when_only_the_group_has_a_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-link1@example.com")
    en, de = await _pair(client)
    await _quiz_for(client, en["id"])

    response = await _link(client, en["translation_group_id"], de["id"])

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "quiz_presence_mismatch"
    assert detail["lacking_side"] == "source"
    assert detail["lacking_module_id"] == de["id"]


async def test_linking_is_refused_when_only_the_source_has_a_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-link2@example.com")
    en, de = await _pair(client)
    await _quiz_for(client, de["id"])

    response = await _link(client, en["translation_group_id"], de["id"])

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["lacking_side"] == "group"
    assert detail["lacking_module_id"] == en["id"]


async def test_linking_succeeds_when_both_or_neither_have_a_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-link3@example.com")
    en, de = await _pair(client)
    assert (await _link(client, en["translation_group_id"], de["id"])).status_code == 201

    en2 = await _make_module(client, title="A", language="en")
    de2 = await _make_module(client, title="B", language="de")
    await _quiz_for(client, en2["id"])
    await _quiz_for(client, de2["id"], pass_mark_percent=50)
    assert (await _link(client, en2["translation_group_id"], de2["id"])).status_code == 201

    # Variants stay independent: each keeps its own settings.
    got = await client.get(f"/api/content/modules/{de2['id']}/quiz")
    assert got.json()["pass_mark_percent"] == 50


# --- Copy from primary ------------------------------------------------------


async def _linked_with_quizzes(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    en, de = await _pair(client)
    await _quiz_for(client, en["id"], pass_mark_percent=70, max_attempts=3, shuffle=True,
                    reveal_after_pass=True)
    assert (await _create_quiz(client, de["id"])).status_code == 200
    assert (await _link(client, en["translation_group_id"], de["id"])).status_code == 201
    return en, de


async def test_copy_from_primary_copies_settings_only_by_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-copy1@example.com")
    _en, de = await _linked_with_quizzes(client)

    response = await client.post(
        f"/api/content/modules/{de['id']}/quiz/copy-from-primary", json={}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["pass_mark_percent"], body["max_attempts"]) == (70, 3)
    assert body["shuffle"] is True and body["reveal_after_pass"] is True
    assert body["questions"] == []


async def test_copy_from_primary_can_copy_questions_with_fresh_ids(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-copy2@example.com")
    en, de = await _linked_with_quizzes(client)
    source = (await client.get(f"/api/content/modules/{en['id']}/quiz")).json()

    response = await client.post(
        f"/api/content/modules/{de['id']}/quiz/copy-from-primary",
        json={"include_questions": True},
    )

    body = response.json()
    assert len(body["questions"]) == 1
    copied, original = body["questions"][0], source["questions"][0]
    assert copied["id"] != original["id"]
    assert copied["prompt"] == original["prompt"]
    assert [(o["text"], o["is_correct"]) for o in copied["options"]] == [
        (o["text"], o["is_correct"]) for o in original["options"]
    ]
    assert {o["id"] for o in copied["options"]}.isdisjoint({o["id"] for o in original["options"]})
    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "quiz_updated"))
    ).scalars()
    assert any(a.detail.get("change") == "copied_from_primary" for a in audit)


async def test_copy_from_primary_is_refused_on_the_primary_itself(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-copy3@example.com")
    en, _ = await _linked_with_quizzes(client)
    response = await client.post(
        f"/api/content/modules/{en['id']}/quiz/copy-from-primary", json={}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "is_primary_variant"


async def test_copy_from_primary_needs_the_primary_to_have_a_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-copy4@example.com")
    en, de = await _pair(client)
    assert (await _link(client, en["translation_group_id"], de["id"])).status_code == 201
    response = await client.post(
        f"/api/content/modules/{de['id']}/quiz/copy-from-primary", json={}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "primary_has_no_quiz"


# --- Duplicate --------------------------------------------------------------


async def test_duplicate_copies_the_draft_quiz_independently(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-dup@example.com")
    module = await _make_module(client, title="Original", language="en")
    await _quiz_for(client, module["id"], pass_mark_percent=65)
    original = (await client.get(f"/api/content/modules/{module['id']}/quiz")).json()

    dup = await client.post(f"/api/content/modules/{module['id']}/duplicate", json={})
    assert dup.status_code == 201, dup.text
    copy_quiz = (await client.get(f"/api/content/modules/{dup.json()['id']}/quiz")).json()

    assert copy_quiz["pass_mark_percent"] == 65
    assert len(copy_quiz["questions"]) == 1
    assert copy_quiz["questions"][0]["id"] != original["questions"][0]["id"]

    # Editing the copy never touches the original.
    await client.delete(
        f"/api/content/modules/{dup.json()['id']}/quiz/questions/{copy_quiz['questions'][0]['id']}"
    )
    again = (await client.get(f"/api/content/modules/{module['id']}/quiz")).json()
    assert len(again["questions"]) == 1


async def test_duplicating_a_module_without_a_quiz_creates_none(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-dup2@example.com")
    module = await _make_module(client, title="Plain", language="en")
    dup = await client.post(f"/api/content/modules/{module['id']}/duplicate", json={})
    assert (await client.get(f"/api/content/modules/{dup.json()['id']}/quiz")).json() is None


# --- Export / import --------------------------------------------------------


async def test_export_import_round_trips_the_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-rt@example.com")
    module = await _make_module(client, title="RT", language="en")
    await _quiz_for(client, module["id"], pass_mark_percent=90, max_attempts=2, shuffle=True)
    await _add_question(
        client,
        module["id"],
        _question("Pick all", type="multiple_choice",
                  options=[_option("a", True), _option("b", True), _option("c")]),
    )
    original = (await client.get(f"/api/content/modules/{module['id']}/quiz")).json()

    archive = await _export(client, module["id"])
    manifest = _read_manifest(archive)
    assert manifest["quiz"]["pass_mark_percent"] == 90
    # No ids or verdicts leak into the manifest beyond the authored content.
    assert "id" not in manifest["quiz"]["questions"][0]

    imported = await _import(client, archive)
    assert imported.status_code == 201, imported.text
    quiz = (await client.get(f"/api/content/modules/{imported.json()['id']}/quiz")).json()

    assert (quiz["pass_mark_percent"], quiz["max_attempts"], quiz["shuffle"]) == (90, 2, True)
    assert len(quiz["questions"]) == 2
    for got, want in zip(quiz["questions"], original["questions"], strict=True):
        assert got["type"] == want["type"] and got["prompt"] == want["prompt"]
        assert [(o["text"], o["is_correct"]) for o in got["options"]] == [
            (o["text"], o["is_correct"]) for o in want["options"]
        ]


async def test_a_module_without_a_quiz_exports_and_imports_without_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-noquiz@example.com")
    module = await _make_module(client, title="None", language="en")
    archive = await _export(client, module["id"])
    assert _read_manifest(archive)["quiz"] is None
    imported = await _import(client, archive)
    assert imported.status_code == 201
    assert (await client.get(f"/api/content/modules/{imported.json()['id']}/quiz")).json() is None


def _hostile(quiz: dict[str, Any]) -> bytes:
    return _build_zip({"module.json": json.dumps(_minimal_manifest(quiz=quiz)).encode()})


def _good_question(**overrides: Any) -> dict[str, Any]:
    question = _question()
    question.update(overrides)
    return question


async def test_hostile_imported_quizzes_are_rejected_and_create_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-hostile@example.com")
    script_prompt = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    }
                ],
            }
        ],
    }
    unknown_node = {"type": "doc", "content": [{"type": "script", "content": []}]}
    base = {"pass_mark_percent": 80, "max_attempts": None, "shuffle": False,
            "reveal_after_pass": False}
    cases: list[dict[str, Any]] = [
        {**base, "questions": [_good_question(prompt=script_prompt)]},
        {**base, "questions": [_good_question(prompt=unknown_node)]},
        {**base, "questions": [_good_question(explanation=script_prompt)]},
        {**base, "questions": [_good_question(schema_version=SCHEMA_VERSION + 99)]},
        {**base, "questions": [_good_question(type="essay")]},
        {**base, "pass_mark_percent": 0, "questions": []},
        {**base, "questions": [_good_question(options=[_option("x")] * 11)]},
        {**base, "valid": True, "questions": []},  # a claim the manifest may not make
        {**base, "questions": [{**_good_question(), "id": "abc"}]},
    ]
    from app.models import Module

    before = len((await db_session.execute(select(Module))).scalars().all())
    for quiz in cases:
        response = await _import(client, _hostile(quiz))
        assert response.status_code == 422, (quiz, response.text)
    after = len((await db_session.execute(select(Module))).scalars().all())
    assert after == before


async def test_an_imported_quiz_is_still_gated_by_the_publish_check(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-gate@example.com")
    quiz = {
        "pass_mark_percent": 80, "max_attempts": None, "shuffle": False,
        "reveal_after_pass": False,
        "questions": [_good_question(options=[_option("a"), _option("a")])],
    }
    imported = await _import(client, _hostile(quiz))
    assert imported.status_code == 201, imported.text
    got = (await client.get(f"/api/content/modules/{imported.json()['id']}/quiz")).json()
    assert got["problems"], "duplicate options must be reported as publish problems"


async def test_archives_from_before_quizzes_still_import(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-legacy@example.com")
    manifest = _minimal_manifest()
    assert "quiz" not in manifest
    response = await _import(client, _build_zip({"module.json": json.dumps(manifest).encode()}))
    assert response.status_code == 201, response.text


async def test_duplicate_and_import_repoint_quiz_images_at_their_own_assets(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.test_module_transfer import _upload
    from tests.test_upload_sniffing import PNG

    await _author(client, db_session, "qt-img@example.com")
    module = await _make_module(client, title="Img", language="en")
    asset = (await _upload(client, module["id"], data=PNG, filename="d.png")).json()["assets"][0]
    url = f"/api/modules/{module['id']}/assets/{asset['id']}"
    prompt = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "see"}]}, {"type": "image", "attrs": {"src": url, "alt": "d"}}]}
    assert (await _create_quiz(client, module["id"])).status_code == 200
    created = await _add_question(client, module["id"], {**_question(), "prompt": prompt})
    assert created.status_code == 201, created.text

    dup = await client.post(f"/api/content/modules/{module['id']}/duplicate", json={})
    imported = await _import(client, await _export(client, module["id"]))
    for copy_id in (dup.json()["id"], imported.json()["id"]):
        got = (await client.get(f"/api/content/modules/{copy_id}/quiz")).json()
        src = got["questions"][0]["prompt"]["content"][1]["attrs"]["src"]
        assert src != url and f"/api/modules/{copy_id}/assets/" in src


async def test_copy_from_a_deleted_primary_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, "qt-delprimary@example.com")
    en, de = await _linked_with_quizzes(client)
    assert (await client.delete(f"/api/content/modules/{en['id']}")).status_code in (200, 204)
    response = await client.post(
        f"/api/content/modules/{de['id']}/quiz/copy-from-primary", json={}
    )
    assert response.status_code == 409

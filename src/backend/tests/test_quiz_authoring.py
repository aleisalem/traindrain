"""Quiz authoring and snapshotting (Release 2, ticket 8).

The properties held down here: a quiz is validated before it can be published,
the published copy is frozen and unaffected by later draft edits, prompts get the
same reject-never-strip treatment as pages, and a try-out grades without leaving
a trace.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.models import AuditLog, Module, ModuleProgress, ModuleQuiz, ModuleVersion
from tests.test_module_publishing import (
    _add_page,
    _doc,
    _login_with_role,
    _make_module,
    _publish,
    _snapshot,
)


def _option(label: str, correct: bool = False) -> dict[str, Any]:
    return {"text": label, "is_correct": correct}


def _question(
    prompt: str = "What is phishing?",
    *,
    type: str = "single_choice",
    options: list[dict[str, Any]] | None = None,
    explanation: str | None = "Because.",
) -> dict[str, Any]:
    if options is None:
        options = [_option("A scam email", True), _option("A fish")]
    return {
        "type": type,
        "schema_version": SCHEMA_VERSION,
        "prompt": _doc(prompt),
        "explanation": _doc(explanation) if explanation else None,
        "options": options,
    }


async def _module(client: AsyncClient, db_session: AsyncSession, email: str) -> str:
    await _login_with_role(client, db_session, email=email, role_name="Content Manager")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    return module_id


async def _create_quiz(client: AsyncClient, module_id: str, **settings: Any) -> Any:
    return await client.put(f"/api/content/modules/{module_id}/quiz", json=settings)


async def _add_question(client: AsyncClient, module_id: str, body: dict[str, Any]) -> Any:
    return await client.post(f"/api/content/modules/{module_id}/quiz/questions", json=body)


async def _valid_quiz(client: AsyncClient, module_id: str) -> dict[str, Any]:
    assert (await _create_quiz(client, module_id)).status_code == 200
    response = await _add_question(client, module_id, _question())
    assert response.status_code == 201, response.text
    return response.json()


# --- Draft CRUD -------------------------------------------------------------


async def test_a_module_without_a_quiz_returns_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-none@example.com")
    response = await client.get(f"/api/content/modules/{module_id}/quiz")
    assert response.status_code == 200
    assert response.json() is None


async def test_a_new_quiz_has_the_default_settings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-defaults@example.com")
    response = await _create_quiz(client, module_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pass_mark_percent"] == 80
    assert body["max_attempts"] is None
    assert body["shuffle"] is False
    assert body["reveal_after_pass"] is False
    assert body["questions"] == []


async def test_settings_are_replaced_by_put(client: AsyncClient, db_session: AsyncSession) -> None:
    module_id = await _module(client, db_session, "quiz-settings@example.com")
    await _create_quiz(client, module_id)
    response = await _create_quiz(
        client, module_id, pass_mark_percent=60, max_attempts=3, shuffle=True, reveal_after_pass=True
    )
    body = response.json()
    assert (body["pass_mark_percent"], body["max_attempts"]) == (60, 3)
    assert body["shuffle"] is True and body["reveal_after_pass"] is True


async def test_out_of_range_settings_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-range@example.com")
    for bad in ({"pass_mark_percent": 0}, {"pass_mark_percent": 101}, {"max_attempts": 0}):
        assert (await _create_quiz(client, module_id, **bad)).status_code == 422
    assert (await _create_quiz(client, module_id, owner="x")).status_code == 422


async def test_questions_can_be_added_edited_reordered_and_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-crud@example.com")
    await _create_quiz(client, module_id)
    first = (await _add_question(client, module_id, _question("One?"))).json()
    both = (await _add_question(client, module_id, _question("Two?"))).json()
    first_id, second_id = (q["id"] for q in both["questions"])
    assert [q["position"] for q in both["questions"]] == [0, 1]

    patched = await client.patch(
        f"/api/content/modules/{module_id}/quiz/questions/{first_id}",
        json={
            "schema_version": SCHEMA_VERSION,
            "prompt": _doc("One, revised?"),
            "options": [_option("Yes", True), _option("No"), _option("Maybe")],
        },
    )
    assert patched.status_code == 200, patched.text
    edited = patched.json()["questions"][0]
    assert edited["prompt"]["content"][0]["content"][0]["text"] == "One, revised?"
    assert [o["text"] for o in edited["options"]] == ["Yes", "No", "Maybe"]
    assert first["questions"][0]["id"] == first_id

    reordered = await client.post(
        f"/api/content/modules/{module_id}/quiz/questions/reorder",
        json={"question_ids": [second_id, first_id]},
    )
    assert [q["id"] for q in reordered.json()["questions"]] == [second_id, first_id]

    deleted = await client.delete(f"/api/content/modules/{module_id}/quiz/questions/{second_id}")
    assert [q["id"] for q in deleted.json()["questions"]] == [first_id]
    assert deleted.json()["questions"][0]["position"] == 0


async def test_reorder_must_name_every_question_once(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-reorder@example.com")
    quiz = await _valid_quiz(client, module_id)
    only = quiz["questions"][0]["id"]
    for ids in ([], [only, only], [str(uuid.uuid4())]):
        response = await client.post(
            f"/api/content/modules/{module_id}/quiz/questions/reorder", json={"question_ids": ids}
        )
        assert response.status_code == 422


async def test_deleting_the_quiz_removes_its_questions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-delete@example.com")
    await _valid_quiz(client, module_id)
    assert (await client.delete(f"/api/content/modules/{module_id}/quiz")).status_code == 204
    assert (await client.get(f"/api/content/modules/{module_id}/quiz")).json() is None
    count = (await db_session.execute(text("select count(*) from quiz_questions"))).scalar_one()
    assert count == 0


async def test_question_routes_need_a_quiz_and_a_question_in_that_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-404@example.com")
    assert (await _add_question(client, module_id, _question())).status_code == 404
    other = await _make_module(client, title="Other")
    await _valid_quiz(client, other)
    foreign = (await client.get(f"/api/content/modules/{other}/quiz")).json()["questions"][0]["id"]
    await _create_quiz(client, module_id)
    response = await client.patch(
        f"/api/content/modules/{module_id}/quiz/questions/{foreign}",
        json={"type": "multiple_choice"},
    )
    assert response.status_code == 404


# --- Permissions ------------------------------------------------------------


async def test_a_learner_cannot_touch_quizzes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-owner@example.com")
    await _valid_quiz(client, module_id)
    client.cookies.clear()
    await _login_with_role(client, db_session, email="quiz-learner@example.com", role_name="Learner")
    base = f"/api/content/modules/{module_id}/quiz"
    assert (await client.get(base)).status_code == 403
    assert (await client.put(base, json={})).status_code == 403
    assert (await client.delete(base)).status_code == 403
    assert (await client.post(f"{base}/tryout", json={"answers": {}})).status_code == 403


async def test_an_unauthenticated_caller_is_refused(client: AsyncClient) -> None:
    response = await client.get(f"/api/content/modules/{uuid.uuid4()}/quiz")
    assert response.status_code == 401


async def test_an_unknown_module_is_a_404(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_with_role(client, db_session, email="quiz-nomod@example.com", role_name="Content Manager")
    assert (await client.get(f"/api/content/modules/{uuid.uuid4()}/quiz")).status_code == 404


async def test_a_deleted_module_cannot_gain_a_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-gone@example.com")
    await _valid_quiz(client, module_id)
    assert (await client.delete(f"/api/content/modules/{module_id}")).status_code == 200
    assert (await _create_quiz(client, module_id)).status_code == 409
    remaining = (
        await db_session.execute(
            select(func.count()).select_from(ModuleQuiz).where(ModuleQuiz.module_id == uuid.UUID(module_id))
        )
    ).scalar_one()
    assert remaining == 0


# --- Prompt validation ------------------------------------------------------


async def test_prompts_with_disallowed_content_are_rejected_never_stripped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-inject@example.com")
    await _create_quiz(client, module_id)
    hostile = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "click",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    }
                ],
            }
        ],
    }
    script = {"type": "doc", "content": [{"type": "script", "content": []}]}
    for bad in (hostile, script, {"type": "paragraph"}):
        body = _question()
        body["prompt"] = bad
        response = await _add_question(client, module_id, body)
        assert response.status_code == 422, response.text
    body = _question()
    body["explanation"] = hostile
    assert (await _add_question(client, module_id, body)).status_code == 422
    quiz = (await client.get(f"/api/content/modules/{module_id}/quiz")).json()
    assert quiz["questions"] == []


async def test_a_wrong_schema_version_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-schema@example.com")
    await _create_quiz(client, module_id)
    body = _question()
    body["schema_version"] = SCHEMA_VERSION + 1
    assert (await _add_question(client, module_id, body)).status_code == 422


async def test_unknown_question_types_and_extra_fields_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-types@example.com")
    await _create_quiz(client, module_id)
    assert (await _add_question(client, module_id, _question(type="essay"))).status_code == 422
    body = _question()
    body["quiz_id"] = str(uuid.uuid4())
    assert (await _add_question(client, module_id, body)).status_code == 422


# --- Publish validation -----------------------------------------------------


async def _publish_problem_codes(client: AsyncClient, module_id: str) -> set[str]:
    response = await _publish(client, module_id)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_quiz"
    return {p["code"] for p in detail["problems"]}


async def test_publish_refuses_a_quiz_with_no_questions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-empty@example.com")
    await _create_quiz(client, module_id)
    assert await _publish_problem_codes(client, module_id) == {"no_questions"}


async def test_publish_validation_matrix(client: AsyncClient, db_session: AsyncSession) -> None:
    module_id = await _module(client, db_session, "quiz-matrix@example.com")
    await _create_quiz(client, module_id)
    cases: list[tuple[dict[str, Any], str]] = [
        (_question(options=[_option("A"), _option("B")]), "correct_answer_count"),
        (_question(options=[_option("A", True), _option("B", True)]), "correct_answer_count"),
        (
            _question(type="multiple_choice", options=[_option("A"), _option("B")]),
            "correct_answer_count",
        ),
        (_question(options=[_option("A", True)]), "too_few_options"),
        (_question(options=[_option("A", True), _option("  ")]), "empty_option"),
        (_question(options=[_option("Same", True), _option("same")]), "duplicate_options"),
        (
            _question(
                type="true_false", options=[_option("true", True), _option("true")]
            ),
            "bad_true_false",
        ),
        (
            _question(
                type="true_false", options=[_option("true", True), _option("false", True)]
            ),
            "correct_answer_count",
        ),
    ]
    for body, expected in cases:
        added = (await _add_question(client, module_id, body)).json()
        question_id = added["questions"][-1]["id"]
        codes = await _publish_problem_codes(client, module_id)
        assert expected in codes, (expected, codes)
        await client.delete(f"/api/content/modules/{module_id}/quiz/questions/{question_id}")

    blank = _question()
    blank["prompt"] = {"type": "doc", "content": [{"type": "paragraph"}]}
    await _add_question(client, module_id, blank)
    assert "empty_prompt" in await _publish_problem_codes(client, module_id)


async def test_a_refused_publish_writes_no_version(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-norefuse@example.com")
    await _create_quiz(client, module_id)
    await _publish(client, module_id)
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ModuleVersion)
            .where(ModuleVersion.module_id == uuid.UUID(module_id))
        )
    ).scalar_one()
    assert count == 0


async def test_every_valid_question_type_publishes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-valid@example.com")
    await _create_quiz(client, module_id)
    await _add_question(client, module_id, _question())
    await _add_question(
        client,
        module_id,
        _question(
            "Pick all", type="multiple_choice", options=[_option("A", True), _option("B", True), _option("C")]
        ),
    )
    await _add_question(
        client,
        module_id,
        _question("Sky is blue", type="true_false", options=[_option("true", True), _option("false")]),
    )
    response = await _publish(client, module_id)
    assert response.status_code == 200, response.text


async def test_the_draft_reports_what_blocks_publishing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-problems@example.com")
    await _create_quiz(client, module_id)
    body = (await client.get(f"/api/content/modules/{module_id}/quiz")).json()
    assert [p["code"] for p in body["problems"]] == ["no_questions"]
    await _add_question(client, module_id, _question())
    body = (await client.get(f"/api/content/modules/{module_id}/quiz")).json()
    assert body["problems"] == []


# --- Snapshotting -----------------------------------------------------------


async def test_publish_freezes_the_quiz_and_later_edits_do_not_change_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-freeze@example.com")
    quiz = await _valid_quiz(client, module_id)
    await _create_quiz(client, module_id, pass_mark_percent=70)
    assert (await _publish(client, module_id)).status_code == 200

    frozen = (await _snapshot(db_session, module_id))["quiz"]
    assert frozen["pass_mark_percent"] == 70
    assert frozen["questions"][0]["id"] == quiz["questions"][0]["id"]
    assert [o["is_correct"] for o in frozen["questions"][0]["options"]] == [True, False]

    await _create_quiz(client, module_id, pass_mark_percent=95)
    qid = quiz["questions"][0]["id"]
    await client.patch(
        f"/api/content/modules/{module_id}/quiz/questions/{qid}",
        json={"options": [_option("X"), _option("Y", True)]},
    )
    await client.delete(f"/api/content/modules/{module_id}/quiz")

    again = (await _snapshot(db_session, module_id))["quiz"]
    assert again == frozen


async def test_a_module_without_a_quiz_snapshots_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-nullsnap@example.com")
    await _publish(client, module_id)
    assert (await _snapshot(db_session, module_id))["quiz"] is None


async def test_the_database_refuses_to_update_a_snapshotted_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-immutable@example.com")
    await _valid_quiz(client, module_id)
    await _publish(client, module_id)
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    try:
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE module_versions SET snapshot = jsonb_set(snapshot, '{quiz}', 'null') WHERE id = :id"),
                {"id": module.current_version_id},
            )
    except Exception as error:  # noqa: BLE001
        assert "immutable" in str(error)
    else:  # pragma: no cover
        raise AssertionError("expected the immutability trigger to refuse the update")


async def test_learner_module_payloads_never_carry_the_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-leak@example.com")
    await _valid_quiz(client, module_id)
    await client.patch(f"/api/content/modules/{module_id}", json={"catalog_visible": True})
    await _publish(client, module_id)
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    response = await client.get(f"/api/me/modules/{module.translation_group_id}")
    assert response.status_code == 200, response.text
    assert "is_correct" not in response.text
    assert "quiz" not in response.json()


# --- Revision impact --------------------------------------------------------


async def _complete(db_session: AsyncSession, module_id: str) -> None:
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    from app.models import User

    learner = (await db_session.execute(select(User).limit(1))).scalar_one()
    db_session.add(
        ModuleProgress(
            user_id=learner.id,
            translation_group_id=module.translation_group_id,
            module_id=module.id,
            pages_viewed=[],
            completed_at=datetime.now(UTC),
            completed_version_number=1,
            completed_module_id=module.id,
        )
    )
    await db_session.commit()


async def _progress(db_session: AsyncSession, module_id: str) -> list[ModuleProgress]:
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    return list(
        (
            await db_session.execute(
                select(ModuleProgress).where(
                    ModuleProgress.translation_group_id == module.translation_group_id
                )
            )
        ).scalars()
    )


async def _impact(client: AsyncClient, module_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/content/modules/{module_id}/revision-impact")
    assert response.status_code == 200
    return response.json()


async def test_revision_impact_tracks_quiz_added_changed_removed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-impact@example.com")
    await _publish(client, module_id)
    await _complete(db_session, module_id)

    assert (await _impact(client, module_id))["quiz_change"] == "none"

    quiz = await _valid_quiz(client, module_id)
    impact = await _impact(client, module_id)
    assert impact["quiz_change"] == "added"
    assert impact["quiz_affected_learners"] == impact["completed_learners"] == 1

    await _publish(client, module_id, kind="substantive")
    assert (await _impact(client, module_id))["quiz_change"] == "none"

    qid = quiz["questions"][0]["id"]
    await client.patch(
        f"/api/content/modules/{module_id}/quiz/questions/{qid}",
        json={"options": [_option("Other", True), _option("Nope")]},
    )
    assert (await _impact(client, module_id))["quiz_change"] == "changed"

    await client.delete(f"/api/content/modules/{module_id}/quiz")
    impact = await _impact(client, module_id)
    assert impact["quiz_change"] == "removed"
    assert impact["quiz_affected_learners"] == 0


async def test_removing_a_quiz_publishes_as_minor_without_disturbing_learners(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-removeminor@example.com")
    await _valid_quiz(client, module_id)
    await _publish(client, module_id)
    await _complete(db_session, module_id)
    await client.delete(f"/api/content/modules/{module_id}/quiz")

    assert (await _publish(client, module_id, kind="minor")).status_code == 200
    assert (await _snapshot(db_session, module_id))["quiz"] is None
    progress = await _progress(db_session, module_id)
    assert progress and all(row.superseded_at is None for row in progress)


async def test_a_substantive_quiz_publish_supersedes_completed_learners(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-super@example.com")
    await _publish(client, module_id)
    await _complete(db_session, module_id)
    await _valid_quiz(client, module_id)
    response = await _publish(client, module_id, kind="substantive")
    assert response.status_code == 200, response.text
    db_session.expire_all()
    progress = await _progress(db_session, module_id)
    assert progress and all(row.superseded_at is not None for row in progress)


# --- Try-out ----------------------------------------------------------------


async def _tryout_fixture(client: AsyncClient, module_id: str) -> dict[str, Any]:
    await _create_quiz(client, module_id, pass_mark_percent=50)
    await _add_question(client, module_id, _question("Single"))
    await _add_question(
        client,
        module_id,
        _question("Multi", type="multiple_choice", options=[_option("A", True), _option("B", True), _option("C")]),
    )
    return (await client.get(f"/api/content/modules/{module_id}/quiz")).json()


def _ids(question: dict[str, Any], *, correct: bool) -> list[str]:
    return [o["id"] for o in question["options"] if o["is_correct"] is correct]


async def test_tryout_grades_server_side_and_records_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-tryout@example.com")
    quiz = await _tryout_fixture(client, module_id)
    single, multi = quiz["questions"]
    before = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()

    response = await client.post(
        f"/api/content/modules/{module_id}/quiz/tryout",
        json={"answers": {single["id"]: _ids(single, correct=True), multi["id"]: _ids(multi, correct=True)}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["correct_count"], body["total"], body["score_percent"]) == (2, 2, 100)
    assert body["passed"] is True

    partial = await client.post(
        f"/api/content/modules/{module_id}/quiz/tryout",
        json={"answers": {single["id"]: _ids(single, correct=True), multi["id"]: _ids(multi, correct=True)[:1]}},
    )
    assert partial.json()["correct_count"] == 1  # a strict subset scores zero
    assert partial.json()["passed"] is True  # 50% meets the 50% pass mark

    wrong = await client.post(
        f"/api/content/modules/{module_id}/quiz/tryout",
        json={"answers": {single["id"]: _ids(single, correct=False)}},
    )
    assert wrong.json()["score_percent"] == 0 and wrong.json()["passed"] is False

    after = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert after == before
    assert await _progress(db_session, module_id) == []


async def test_tryout_rejects_foreign_question_and_option_ids(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-forged@example.com")
    quiz = await _tryout_fixture(client, module_id)
    single, multi = quiz["questions"]
    url = f"/api/content/modules/{module_id}/quiz/tryout"
    assert (await client.post(url, json={"answers": {str(uuid.uuid4()): []}})).status_code == 422
    cross = {single["id"]: [multi["options"][0]["id"]]}
    assert (await client.post(url, json={"answers": cross})).status_code == 422


async def test_tryout_needs_questions(client: AsyncClient, db_session: AsyncSession) -> None:
    module_id = await _module(client, db_session, "quiz-tryempty@example.com")
    await _create_quiz(client, module_id)
    response = await client.post(f"/api/content/modules/{module_id}/quiz/tryout", json={"answers": {}})
    assert response.status_code == 409


# --- Audit ------------------------------------------------------------------


async def test_quiz_changes_and_publishes_are_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _module(client, db_session, "quiz-audit@example.com")
    await _valid_quiz(client, module_id)
    await _publish(client, module_id)
    entries = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action.in_(["quiz_updated", "module_published"]))
        )
    ).scalars().all()
    entries = [e for e in entries if e.detail.get("module_id") == module_id]
    changes = [e.detail["change"] for e in entries if e.action == "quiz_updated"]
    assert changes == ["created", "question_added"]
    published = next(e for e in entries if e.action == "module_published")
    assert published.detail["quiz_change"] == "added"
    assert published.detail["quiz_question_count"] == 1

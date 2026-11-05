"""Attempt administration and erase (Release 2, ticket 11).

What is held down: only an Administrator resets attempts, and it is audited;
the cap and a prior pass follow the learner across translation variants; and
erasing a user hard-deletes their answers while their scores stay in the figures.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Module, ModuleProgress, QuizAttempt, User
from app.quiz_attempts import attempt_aggregates
from tests.test_learner_viewer import (
    _become_learner,
    _login,
    _login_with_role,
    _open,
    _view_every_page,
)
from tests.test_module_publishing import _add_page, _publish
from tests.test_quiz_authoring import _add_question, _create_quiz, _option, _question
from tests.test_quiz_taking import Quiz, _publish_quiz_module, _ready, _start, _take


async def _admin(client: AsyncClient, db_session: AsyncSession, email: str) -> User:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    return await _login_with_role(client, db_session, email=email, role_name="Administrator")


async def _reset(client: AsyncClient, module_id: str, user_id: Any) -> Any:
    return await client.post(
        f"/api/content/modules/{module_id}/quiz/attempts/reset", json={"user_id": str(user_id)}
    )


async def _learner_id(db_session: AsyncSession, email: str) -> uuid.UUID:
    return (await db_session.execute(select(User.id).where(User.email == email))).scalar_one()


# --- Reset ---------------------------------------------------------------------


async def test_an_administrator_reset_restores_an_exhausted_learner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "rs1", max_attempts=1)
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set()))
    assert (await _start(client, quiz)).status_code == 409
    learner_id = await _learner_id(db_session, "rs1-learner@example.com")

    admin = await _admin(client, db_session, "rs1-admin@example.com")
    response = await _reset(client, quiz.module_id, learner_id)
    assert response.status_code == 200, response.text
    assert response.json() == {"attempts_deleted": 1}

    entry = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "quiz_attempts_reset")
        )
    ).scalar_one()
    assert entry.actor_user_id == admin.id and entry.target_user_id == learner_id
    assert entry.detail["module_id"] == quiz.module_id

    await _login(client, email="rs1-learner@example.com")
    assert (await _start(client, quiz)).status_code == 200


async def test_reset_is_administrator_only_and_validates_the_learner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "rs2", max_attempts=1)
    learner_id = await _learner_id(db_session, "rs2-learner@example.com")
    # The learner themselves.
    assert (await _reset(client, quiz.module_id, learner_id)).status_code == 403
    # A Content Manager, the module's author included.
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="rs2-author@example.com")
    assert (await _reset(client, quiz.module_id, learner_id)).status_code == 403
    assert (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "quiz_attempts_reset"))
    ).first() is None

    await _admin(client, db_session, "rs2-admin@example.com")
    assert (await _reset(client, quiz.module_id, uuid.uuid4())).status_code == 404
    assert (await _reset(client, str(uuid.uuid4()), learner_id)).status_code == 404

    await client.post("/api/auth/logout")
    client.cookies.clear()
    assert (await _reset(client, quiz.module_id, learner_id)).status_code in (401, 403)


async def test_reset_leaves_the_completion_record_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "rs3")
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right={"Single?", "Multi?", "Bool?"}))
    done = await client.post(f"/api/me/modules/{quiz.group_id}/complete")
    assert done.status_code == 200, done.text
    learner_id = await _learner_id(db_session, "rs3-learner@example.com")

    await _admin(client, db_session, "rs3-admin@example.com")
    assert (await _reset(client, quiz.module_id, learner_id)).json()["attempts_deleted"] == 1

    progress = (
        await db_session.execute(select(ModuleProgress).where(ModuleProgress.user_id == learner_id))
    ).scalar_one()
    assert progress.completed_at is not None and progress.completed_score_percent == 100


# --- Cap across translations -----------------------------------------------------


async def _publish_variant(client: AsyncClient, *, language: str, title: str) -> tuple[str, Quiz]:
    module = await client.post(
        "/api/content/modules",
        json={"title": title, "description": "d", "language": language},
    )
    module_id = module.json()["id"]
    await _add_page(client, module_id, title="Intro", revision=1)
    await client.patch(f"/api/content/modules/{module_id}", json={"catalog_visible": True})
    assert (await _create_quiz(client, module_id, max_attempts=2)).status_code == 200
    body = _question("Single?", options=[_option("Right", True), _option("Wrong")])
    assert (await _add_question(client, module_id, body)).status_code == 201
    return module_id, Quiz(module_id, "", {}, [])


async def _two_language_quiz(
    client: AsyncClient, db_session: AsyncSession, slug: str
) -> tuple[str, dict[str, dict[str, Any]]]:
    """A published EN+DE material with a cap of two; returns the group id and
    each language's question/option ids (the key an author sees)."""
    await _login_with_role(
        client, db_session, email=f"{slug}-author@example.com", role_name="Content Manager"
    )
    en_id, _ = await _publish_variant(client, language="en", title="Phishing")
    de_id, _ = await _publish_variant(client, language="de", title="Phishing DE")
    en = (await client.get(f"/api/content/modules/{en_id}")).json()
    linked = await client.post(
        f"/api/content/translation-groups/{en['translation_group_id']}/variants",
        json={"module_id": de_id},
    )
    assert linked.status_code == 201, linked.text
    keys: dict[str, dict[str, Any]] = {}
    for language, module_id in (("en", en_id), ("de", de_id)):
        assert (await _publish(client, module_id)).status_code == 200
        question = (await client.get(f"/api/content/modules/{module_id}/quiz")).json()["questions"][0]
        keys[language] = {
            "question": question["id"],
            "right": [o["id"] for o in question["options"] if o["is_correct"]],
            "wrong": [o["id"] for o in question["options"] if not o["is_correct"]],
        }
    return en["translation_group_id"], keys


async def _attempt(client: AsyncClient, group: str, key: dict[str, Any], *, right: bool) -> Any:
    base = f"/api/me/modules/{group}/quiz"
    started = await client.post(f"{base}/attempts")
    assert started.status_code == 200, started.text
    attempt_id = started.json()["attempt"]["id"]
    await client.put(
        f"{base}/attempts/{attempt_id}/answers/{key['question']}",
        json={"option_ids": key["right" if right else "wrong"]},
    )
    submitted = await client.post(f"{base}/attempts/{attempt_id}/submit")
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


async def _read_everything(client: AsyncClient, group: str) -> None:
    opened = (await _open(client, group)).json()
    await _view_every_page(client, group, opened["pages"])


async def test_switching_language_does_not_dodge_the_attempt_cap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group, keys = await _two_language_quiz(client, db_session, "xv1")
    await _become_learner(client, db_session, email="xv1-learner@example.com")
    await _read_everything(client, group)
    await _attempt(client, group, keys["en"], right=False)
    await _attempt(client, group, keys["en"], right=False)

    switched = await client.post(f"/api/me/modules/{group}/language", json={"language": "de"})
    assert switched.status_code == 200, switched.text
    await _read_everything(client, group)

    state = (await client.get(f"/api/me/modules/{group}/quiz")).json()["summary"]
    assert state["attempts_used"] == 2 and state["exhausted"] is True
    refused = await client.post(f"/api/me/modules/{group}/quiz/attempts")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "attempts_exhausted"


async def test_a_prior_pass_survives_a_language_switch(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group, keys = await _two_language_quiz(client, db_session, "xv2")
    await _become_learner(client, db_session, email="xv2-learner@example.com")
    await _read_everything(client, group)
    assert (await _attempt(client, group, keys["en"], right=True))["attempt"]["result"]["passed"]

    await client.post(f"/api/me/modules/{group}/language", json={"language": "de"})
    await _read_everything(client, group)

    summary = (await client.get(f"/api/me/modules/{group}/quiz")).json()["summary"]
    assert summary["passed"] is True and summary["attempts_used"] == 1
    assert (await client.post(f"/api/me/modules/{group}/complete")).status_code == 200


async def test_reset_clears_attempts_in_every_language(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group, keys = await _two_language_quiz(client, db_session, "xv3")
    await _become_learner(client, db_session, email="xv3-learner@example.com")
    await _read_everything(client, group)
    await _attempt(client, group, keys["en"], right=False)
    await client.post(f"/api/me/modules/{group}/language", json={"language": "de"})
    await _read_everything(client, group)
    await _attempt(client, group, keys["de"], right=False)
    learner_id = await _learner_id(db_session, "xv3-learner@example.com")
    module = (
        await db_session.execute(select(Module).where(Module.translation_group_id == uuid.UUID(group)))
    ).scalars().first()
    assert module is not None

    await _admin(client, db_session, "xv3-admin@example.com")
    assert (await _reset(client, str(module.id), learner_id)).json()["attempts_deleted"] == 2
    await _login(client, email="xv3-learner@example.com")
    state = (await client.get(f"/api/me/modules/{group}/quiz")).json()["summary"]
    assert state["attempts_used"] == 0


# --- Erase -----------------------------------------------------------------------


async def test_erase_deletes_answers_but_keeps_scores_and_completion(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "er1")
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set()))
    await _take(client, quiz, quiz.answers(right={"Single?", "Multi?", "Bool?"}))
    assert (await client.post(f"/api/me/modules/{quiz.group_id}/complete")).status_code == 200
    # A second learner, so the aggregates have someone who is not erased.
    other_id = (await _become_learner(client, db_session, email="er1-other@example.com")).id
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right={"Single?", "Multi?"}))
    group_id = uuid.UUID(quiz.group_id)
    before = await attempt_aggregates(db_session, group_id)
    assert before["attempts"] == 3 and before["passed"] == 1

    learner_id = await _learner_id(db_session, "er1-learner@example.com")
    await _admin(client, db_session, "er1-admin@example.com")
    erased = await client.post(f"/api/admin/users/{learner_id}/erase")
    assert erased.status_code == 204

    db_session.expire_all()
    rows = (
        await db_session.execute(select(QuizAttempt).where(QuizAttempt.user_id == learner_id))
    ).scalars().all()
    assert len(rows) == 2
    for row in rows:
        assert row.answers == {} and row.submitted_at is not None
        assert row.score_percent is not None and row.passed is not None
        assert row.version_number == 1
    assert other_id != learner_id
    assert await attempt_aggregates(db_session, group_id) == before
    progress = (
        await db_session.execute(select(ModuleProgress).where(ModuleProgress.user_id == learner_id))
    ).scalar_one()
    assert progress.completed_at is not None and progress.completed_score_percent == 100


async def test_erase_deletes_an_attempt_in_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "er2")
    await _ready(client, quiz)
    started = await _start(client, quiz)
    attempt_id = started.json()["attempt"]["id"]
    learner_id = await _learner_id(db_session, "er2-learner@example.com")

    await _admin(client, db_session, "er2-admin@example.com")
    assert (await client.post(f"/api/admin/users/{learner_id}/erase")).status_code == 204

    db_session.expire_all()
    assert await db_session.get(QuizAttempt, uuid.UUID(attempt_id)) is None

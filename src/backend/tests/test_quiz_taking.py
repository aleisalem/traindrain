"""Quiz-taking, grading and completion gating (Release 2, ticket 9).

What is held down: the server grades and no learner payload ever carries a key
(except the reveal, after a pass, when the author allowed it); an attempt is
validated against its own frozen question set; the cap and the rate limit bind;
completion needs pages, then a pass, then the attestation; and a republish
mid-attempt does not disturb the attempt.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, ModuleProgress, QuizAttempt
from tests.test_learner_viewer import (
    _become_learner,
    _login,
    _login_with_role,
    _open,
    _view_every_page,
)
from tests.test_module_publishing import _add_page, _make_module, _publish
from tests.test_quiz_authoring import _add_question, _create_quiz, _option, _question


class Quiz:
    """A published module with a three-question quiz, and the key to it."""

    def __init__(self, module_id: str, group_id: str, key: dict[str, Any], pages: list[dict[str, Any]]):
        self.module_id = module_id
        self.group_id = group_id
        # question prompt text -> {"id", "type", "correct": [ids], "wrong": [ids]}
        self.key = key
        self.pages = pages

    def base(self) -> str:
        return f"/api/me/modules/{self.group_id}/quiz"

    def answers(self, *, right: set[str]) -> dict[str, list[str]]:
        """Correct answers for the named questions, a wrong one for the rest."""
        return {
            q["id"]: q["correct"] if name in right else q["wrong"][:1]
            for name, q in self.key.items()
        }


async def _publish_quiz_module(
    client: AsyncClient,
    db_session: AsyncSession,
    slug: str,
    **settings: Any,
) -> Quiz:
    await _login_with_role(
        client, db_session, email=f"{slug}-author@example.com", role_name="Content Manager"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    await _add_page(client, module_id, title="More", revision=2)
    await client.patch(f"/api/content/modules/{module_id}", json={"catalog_visible": True})
    assert (await _create_quiz(client, module_id, **settings)).status_code == 200
    for body in (
        _question("Single?", options=[_option("Right", True), _option("Wrong"), _option("Also wrong")]),
        _question(
            "Multi?",
            type="multiple_choice",
            options=[_option("A", True), _option("B", True), _option("C"), _option("D")],
        ),
        _question(
            "Bool?",
            type="true_false",
            options=[_option("true", True), _option("false")],
        ),
    ):
        assert (await _add_question(client, module_id, body)).status_code == 201
    published = await _publish(client, module_id)
    assert published.status_code == 200, published.text

    quiz = (await client.get(f"/api/content/modules/{module_id}/quiz")).json()
    key = {}
    for question in quiz["questions"]:
        name = question["prompt"]["content"][0]["content"][0]["text"]
        key[name] = {
            "id": question["id"],
            "type": question["type"],
            "correct": [o["id"] for o in question["options"] if o["is_correct"]],
            "wrong": [o["id"] for o in question["options"] if not o["is_correct"]],
        }
    module = await db_session.get(Module, uuid.UUID(module_id))
    assert module is not None
    group_id = str(module.translation_group_id)
    await _become_learner(client, db_session, email=f"{slug}-learner@example.com")
    opened = (await _open(client, group_id)).json()
    return Quiz(module_id, group_id, key, opened["pages"])


async def _start(client: AsyncClient, quiz: Quiz) -> Any:
    return await client.post(f"{quiz.base()}/attempts")


async def _answer(client: AsyncClient, quiz: Quiz, attempt_id: str, qid: str, ids: list[str]) -> Any:
    return await client.put(
        f"{quiz.base()}/attempts/{attempt_id}/answers/{qid}", json={"option_ids": ids}
    )


async def _take(
    client: AsyncClient, quiz: Quiz, answers: dict[str, list[str]]
) -> dict[str, Any]:
    started = await _start(client, quiz)
    assert started.status_code == 200, started.text
    attempt_id = started.json()["attempt"]["id"]
    for qid, ids in answers.items():
        assert (await _answer(client, quiz, attempt_id, qid, ids)).status_code == 200
    submitted = await client.post(f"{quiz.base()}/attempts/{attempt_id}/submit")
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


async def _ready(client: AsyncClient, quiz: Quiz) -> None:
    await _view_every_page(client, quiz.group_id, quiz.pages)


# --- Payload safety -----------------------------------------------------------


async def test_no_learner_payload_carries_correctness_before_a_pass(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "leak", reveal_after_pass=True)
    await _ready(client, quiz)
    started = await _start(client, quiz)
    assert "is_correct" not in started.text
    assert "correct_option_ids" not in started.text
    assert "explanation" not in started.text.replace('"explanation":null', "")
    module_text = (await _open(client, quiz.group_id)).text
    assert "is_correct" not in module_text

    # A failed attempt flags wrong questions but still reveals no key.
    attempt_id = started.json()["attempt"]["id"]
    failed = await client.post(f"{quiz.base()}/attempts/{attempt_id}/submit")
    assert failed.json()["attempt"]["result"]["passed"] is False
    assert failed.json()["attempt"]["result"]["revealed"] is None
    assert "correct_option_ids" not in failed.text


async def test_reveal_only_after_a_pass_and_only_if_enabled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "reveal", reveal_after_pass=True)
    await _ready(client, quiz)
    state = await _take(client, quiz, quiz.answers(right=set(quiz.key)))
    result = state["attempt"]["result"]
    assert result["passed"] is True and result["score_percent"] == 100
    revealed = {r["question_id"]: r for r in result["revealed"]}
    single = quiz.key["Single?"]
    assert revealed[single["id"]]["correct_option_ids"] == single["correct"]
    assert revealed[single["id"]]["explanation"] is not None


async def test_a_pass_does_not_reveal_when_the_author_did_not_allow_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "noreveal")
    await _ready(client, quiz)
    state = await _take(client, quiz, quiz.answers(right=set(quiz.key)))
    assert state["attempt"]["result"]["passed"] is True
    assert state["attempt"]["result"]["revealed"] is None
    assert "correct_option_ids" not in str(state)


# --- Grading ------------------------------------------------------------------


async def test_grading_covers_all_three_question_types(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "grading", pass_mark_percent=60)
    await _ready(client, quiz)
    multi = quiz.key["Multi?"]
    answers = quiz.answers(right={"Single?", "Bool?"})
    # A strict subset of a multiple-choice key scores zero.
    answers[multi["id"]] = multi["correct"][:1]
    state = await _take(client, quiz, answers)
    result = state["attempt"]["result"]
    assert result["correct_count"] == 2 and result["total"] == 3
    assert result["score_percent"] == 67 and result["passed"] is True
    outcomes = {o["question_id"]: o["correct"] for o in result["questions"]}
    assert outcomes[multi["id"]] is False
    assert outcomes[quiz.key["Single?"]["id"]] is True


async def test_a_superset_of_a_multiple_choice_key_is_wrong(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "superset", pass_mark_percent=100)
    await _ready(client, quiz)
    multi = quiz.key["Multi?"]
    answers = quiz.answers(right=set(quiz.key))
    answers[multi["id"]] = multi["correct"] + multi["wrong"][:1]
    state = await _take(client, quiz, answers)
    assert state["attempt"]["result"]["passed"] is False


# --- Forged input ---------------------------------------------------------------


async def test_forged_and_foreign_ids_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "forge")
    other = await _publish_quiz_module(client, db_session, "forge-other")
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="forge-learner@example.com")
    await _ready(client, quiz)
    attempt_id = (await _start(client, quiz)).json()["attempt"]["id"]
    single = quiz.key["Single?"]

    # A question that belongs to some other quiz.
    foreign_q = other.key["Single?"]["id"]
    assert (await _answer(client, quiz, attempt_id, foreign_q, [])).status_code == 404
    # An option that belongs to a different question of this quiz.
    other_question_option = quiz.key["Bool?"]["correct"]
    assert (await _answer(client, quiz, attempt_id, single["id"], other_question_option)).status_code == 422
    assert (
        await _answer(client, quiz, attempt_id, single["id"], [str(uuid.uuid4())])
    ).status_code == 422
    # Two answers to a single-choice question.
    assert (await _answer(client, quiz, attempt_id, single["id"], single["correct"] + single["wrong"][:1])).status_code == 422
    # Extra fields are refused.
    forged = await client.put(
        f"{quiz.base()}/attempts/{attempt_id}/answers/{single['id']}",
        json={"option_ids": [], "score_percent": 100},
    )
    assert forged.status_code == 422


async def test_another_learners_attempt_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "idor")
    await _ready(client, quiz)
    attempt_id = (await _start(client, quiz)).json()["attempt"]["id"]
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login_with_role(client, db_session, email="idor-intruder@example.com", role_name="Learner")
    # The intruder cannot reach the material at all; and even via the catalog
    # (it is catalog-visible) the attempt id is not theirs.
    single = quiz.key["Single?"]
    assert (await _answer(client, quiz, attempt_id, single["id"], single["correct"])).status_code == 404
    assert (await client.post(f"{quiz.base()}/attempts/{attempt_id}/submit")).status_code == 404


# --- Attempts: resume, cap, rate limit ---------------------------------------------


async def test_an_open_attempt_is_resumed_with_its_saved_answers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "resume", shuffle=True)
    await _ready(client, quiz)
    first = (await _start(client, quiz)).json()["attempt"]
    single = quiz.key["Single?"]
    await _answer(client, quiz, first["id"], single["id"], single["correct"])

    again = (await _start(client, quiz)).json()["attempt"]
    assert again["id"] == first["id"]
    assert again["answers"] == {single["id"]: single["correct"]}
    # The shuffle seed is stored, so the order survives a reload.
    assert [q["id"] for q in again["questions"]] == [q["id"] for q in first["questions"]]
    assert (await client.get(quiz.base())).json()["attempt"]["id"] == first["id"]
    assert await _attempt_count(db_session) == 1


async def _attempt_count(db_session: AsyncSession) -> int:
    return len(list((await db_session.execute(select(QuizAttempt))).scalars()))


async def test_the_attempt_cap_is_enforced_with_a_clear_exhausted_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "cap", max_attempts=2)
    await _ready(client, quiz)
    first = await _take(client, quiz, quiz.answers(right=set()))
    assert first["summary"]["attempts_remaining"] == 1
    second = await _take(client, quiz, quiz.answers(right=set()))
    assert second["summary"]["attempts_remaining"] == 0
    assert second["summary"]["exhausted"] is True

    third = await _start(client, quiz)
    assert third.status_code == 409
    assert third.json()["detail"]["code"] == "attempts_exhausted"


async def test_submissions_are_rate_limited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "rate")
    await _ready(client, quiz)
    for _ in range(5):
        await _take(client, quiz, quiz.answers(right=set()))
    started = await _start(client, quiz)
    attempt_id = started.json()["attempt"]["id"]
    blocked = await client.post(f"{quiz.base()}/attempts/{attempt_id}/submit")
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "too_many_submissions"


async def test_a_submitted_attempt_cannot_be_changed_or_resubmitted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "twice")
    await _ready(client, quiz)
    state = await _take(client, quiz, quiz.answers(right=set()))
    attempt_id = state["attempt"]["id"]
    single = quiz.key["Single?"]
    changed = await _answer(client, quiz, attempt_id, single["id"], single["correct"])
    assert changed.status_code == 409
    assert (await client.post(f"{quiz.base()}/attempts/{attempt_id}/submit")).status_code == 409


# --- Completion gating -------------------------------------------------------------


async def test_a_module_without_a_quiz_is_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.test_learner_viewer import _publish_module

    module = await _publish_module(client, db_session, author_email="plain-author@example.com")
    await _become_learner(client, db_session, email="plain-learner@example.com")
    group = module.get("translation_group_id")
    if group is None:
        row = await db_session.get(Module, uuid.UUID(module["id"]))
        assert row is not None
        group = str(row.translation_group_id)
    opened = (await _open(client, group)).json()
    assert opened["quiz"] is None
    await _view_every_page(client, group, opened["pages"])
    done = await client.post(f"/api/me/modules/{group}/complete")
    assert done.status_code == 200
    assert done.json()["completed_score_percent"] is None
    assert (await client.get(f"/api/me/modules/{group}/quiz")).status_code == 404


async def test_the_quiz_cannot_be_started_before_every_page_is_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "early")
    refused = await _start(client, quiz)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "pages_outstanding"
    await client.post(f"/api/me/modules/{quiz.group_id}/pages/{quiz.pages[0]['id']}/view")
    assert (await _start(client, quiz)).status_code == 409


async def test_completion_order_is_pages_then_pass_then_attestation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "order")
    complete = f"/api/me/modules/{quiz.group_id}/complete"

    pages = await client.post(complete)
    assert pages.status_code == 409 and pages.json()["detail"]["code"] == "pages_outstanding"

    await _ready(client, quiz)
    no_pass = await client.post(complete)
    assert no_pass.status_code == 409 and no_pass.json()["detail"]["code"] == "quiz_not_passed"

    await _take(client, quiz, quiz.answers(right=set()))
    assert (await client.post(complete)).status_code == 409

    await _take(client, quiz, quiz.answers(right={"Single?", "Multi?", "Bool?"}))
    done = await client.post(complete)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["completed_score_percent"] == 100
    assert body["completed_quiz_version_number"] == 1
    assert body["completed_at"] is not None

    # A completed learner cannot farm further attempts.
    again = await _start(client, quiz)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "quiz_already_passed"


# --- Retake ------------------------------------------------------------------------


async def test_retake_quiz_only_keeps_page_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "retake-q")
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set()))

    retaken = await client.post(f"{quiz.base()}/retake", json={"mode": "quiz"})
    assert retaken.status_code == 200, retaken.text
    assert retaken.json()["attempt"]["submitted_at"] is None
    progress = (await _open(client, quiz.group_id)).json()["progress"]
    assert len(progress["pages_viewed"]) == len(quiz.pages)


async def test_retake_module_clears_page_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "retake-m")
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set()))

    retaken = await client.post(f"{quiz.base()}/retake", json={"mode": "module"})
    assert retaken.status_code == 200, retaken.text
    progress = (await _open(client, quiz.group_id)).json()["progress"]
    assert progress["pages_viewed"] == []
    # Pages must be read again before the next attempt.
    assert (await _start(client, quiz)).status_code == 409


async def test_retake_needs_a_failed_attempt_and_a_valid_mode(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "retake-bad")
    await _ready(client, quiz)
    nothing = await client.post(f"{quiz.base()}/retake", json={"mode": "quiz"})
    assert nothing.status_code == 409 and nothing.json()["detail"]["code"] == "nothing_to_retake"
    assert (await client.post(f"{quiz.base()}/retake", json={"mode": "x"})).status_code == 422

    await _take(client, quiz, quiz.answers(right=set(quiz.key)))
    passed = await client.post(f"{quiz.base()}/retake", json={"mode": "module"})
    assert passed.status_code == 409


# --- Republish ---------------------------------------------------------------------


async def _author_republish(
    client: AsyncClient, db_session: AsyncSession, quiz: Quiz, slug: str, *, change: bool, kind: str
) -> None:
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=f"{slug}-author@example.com")
    if change:
        questions = (await client.get(f"/api/content/modules/{quiz.module_id}/quiz")).json()["questions"]
        await _add_question(client, quiz.module_id, _question("Extra?"))
        assert questions
    published = await _publish(client, quiz.module_id, kind=kind)
    assert published.status_code == 200, published.text
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email=f"{slug}-learner@example.com")


async def test_a_republish_mid_attempt_does_not_invalidate_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "mid")
    await _ready(client, quiz)
    first = (await _start(client, quiz)).json()["attempt"]
    await _author_republish(client, db_session, quiz, "mid", change=True, kind="minor")

    resumed = (await _start(client, quiz)).json()
    assert resumed["attempt"]["id"] == first["id"]
    assert len(resumed["attempt"]["questions"]) == 3  # the version they started
    for q in quiz.key.values():
        await _answer(client, quiz, first["id"], q["id"], q["correct"])
    submitted = await client.post(f"{quiz.base()}/attempts/{first['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["attempt"]["result"]["passed"] is True
    assert submitted.json()["attempt"]["version_number"] == 1


async def test_old_attempts_do_not_count_toward_a_new_versions_cap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "newcap", max_attempts=1)
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set()))
    assert (await _start(client, quiz)).status_code == 409

    await _author_republish(client, db_session, quiz, "newcap", change=True, kind="substantive")
    opened = (await _open(client, quiz.group_id)).json()
    assert opened["quiz"]["attempts_used"] == 0
    await _view_every_page(client, quiz.group_id, opened["pages"])
    started = await _start(client, quiz)
    assert started.status_code == 200, started.text
    assert started.json()["attempt"]["version_number"] == 2
    assert len(started.json()["attempt"]["questions"]) == 4


async def test_a_pass_stops_counting_when_the_quiz_changes_but_not_when_it_does_not(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "stale")
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set(quiz.key)))

    # Same quiz, new version: the pass still counts.
    await _author_republish(client, db_session, quiz, "stale", change=False, kind="minor")
    done = await client.post(f"/api/me/modules/{quiz.group_id}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["completed_quiz_version_number"] == 1

    # Changed quiz: the old pass no longer counts.
    await _author_republish(client, db_session, quiz, "stale", change=True, kind="substantive")
    opened = (await _open(client, quiz.group_id)).json()
    assert opened["quiz"]["passed"] is False
    await _view_every_page(client, quiz.group_id, opened["pages"])
    refused = await client.post(f"/api/me/modules/{quiz.group_id}/complete")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "quiz_not_passed"


async def test_attempts_are_stored_with_their_evidence(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "evidence")
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right={"Single?"}))
    db_session.expire_all()
    attempt = (await db_session.execute(select(QuizAttempt))).scalar_one()
    assert attempt.version_number == 1 and attempt.score_percent == 33
    assert attempt.submitted_at is not None and attempt.passed is False
    assert set(attempt.answers) == {q["id"] for q in quiz.key.values()}
    assert isinstance(attempt.shuffle_seed, int)
    progress = (await db_session.execute(select(ModuleProgress))).scalars().first()
    assert progress is not None and progress.completed_at is None


async def test_unauthenticated_access_is_refused(client: AsyncClient) -> None:
    group = uuid.uuid4()
    assert (await client.get(f"/api/me/modules/{group}/quiz")).status_code == 401
    assert (await client.post(f"/api/me/modules/{group}/quiz/attempts")).status_code == 401




async def test_an_open_attempt_survives_the_quiz_being_removed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "removed")
    await _ready(client, quiz)
    attempt = (await _start(client, quiz)).json()["attempt"]
    for q in quiz.key.values():
        await _answer(client, quiz, attempt["id"], q["id"], q["correct"])

    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="removed-author@example.com")
    assert (await client.delete(f"/api/content/modules/{quiz.module_id}/quiz")).status_code in (200, 204)
    assert (await _publish(client, quiz.module_id)).status_code == 200
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login(client, email="removed-learner@example.com")

    state = await client.get(quiz.base())
    assert state.status_code == 200, state.text
    assert state.json()["attempt"]["id"] == attempt["id"]
    submitted = await client.post(f"{quiz.base()}/attempts/{attempt['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["attempt"]["result"]["passed"] is True


async def test_retaking_the_module_is_refused_when_no_attempts_remain(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    quiz = await _publish_quiz_module(client, db_session, "exh-mod", max_attempts=1)
    await _ready(client, quiz)
    await _take(client, quiz, quiz.answers(right=set()))
    refused = await client.post(f"{quiz.base()}/retake", json={"mode": "module"})
    assert refused.status_code == 409
    assert (await _open(client, quiz.group_id)).json()["progress"]["pages_viewed"]

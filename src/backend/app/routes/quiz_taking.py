"""A learner takes a module's quiz: start or resume, answer, submit, retake.

Every route resolves the learner's readable variant through the same decision
the viewer uses, so a quiz is exactly as reachable as the pages it follows. The
quiz *being graded* is always the one frozen into the attempt's own version —
never the module's current one — so a republish mid-attempt cannot invalidate it.

The server grades; the only correctness data that ever leaves it is a per-question
right/wrong flag after a submission, and the key itself after a pass when the
author allowed that (`app.quiz_attempts.attempt_view`).
"""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import require_active_user
from app.models import Module, ModuleProgress, ModuleVersion, QuizAttempt, User
from app.quiz import grade
from app.quiz_attempts import (
    SUBMIT_LIMIT,
    attempt_view,
    attempts_used,
    best_counting_pass,
    latest_submitted,
    open_attempt,
    quiz_summary,
    snapshot_quiz,
    submissions_in_window,
)
from app.routes.learning import (
    _claim_progress,
    _learner_reach,
    _resolve_readable_variant,
    _snapshot_pages,
)
from app.schemas.quiz_taking import AnswerRequest, QuizState, RetakeRequest

router = APIRouter(prefix="/api/me/modules/{translation_group_id}/quiz", tags=["quiz-taking"])


def _conflict(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **extra},
    )


async def _resolve(
    db: AsyncSession, user: User, group_id: uuid.UUID
) -> tuple[Module, ModuleVersion, dict[str, Any]]:
    reach = await _learner_reach(db, user)
    module, version = await _resolve_readable_variant(db, user, group_id, reach)
    quiz = snapshot_quiz(version)
    if quiz is None:
        # An in-flight attempt on an earlier version is still finishable; those
        # routes load their own version. Starting needs a quiz on this one.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "no_quiz", "message": "This module has no quiz."},
        )
    return module, version, quiz


async def _state(
    db: AsyncSession,
    user: User,
    group_id: uuid.UUID,
    version: ModuleVersion,
    attempt: QuizAttempt | None,
) -> QuizState:
    if attempt is None:
        attempt = await open_attempt(db, user, group_id) or await latest_submitted(
            db, user, group_id, version.id
        )
    view = None
    summary_version = version
    if attempt is not None:
        attempt_version = (
            version
            if attempt.version_id == version.id
            else await db.get(ModuleVersion, attempt.version_id)
        )
        attempt_quiz = snapshot_quiz(attempt_version) if attempt_version else None
        if attempt_version is not None and attempt_quiz is not None:
            view = attempt_view(attempt, attempt_quiz)
            # An attempt on a version whose quiz has since been removed is still
            # finishable, so its summary comes from the version it belongs to.
            if snapshot_quiz(version) is None:
                summary_version = attempt_version
    summary = await quiz_summary(db, user, group_id, summary_version)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "no_quiz", "message": "This module has no quiz."},
        )
    return QuizState(summary=summary, attempt=view)


async def _begin_attempt(
    db: AsyncSession, user: User, module: Module, version: ModuleVersion, quiz: dict[str, Any]
) -> QuizAttempt:
    """Resume the open attempt, or create one if the rules allow it.

    The progress row is locked first, which serializes two tabs both pressing
    "start" so they get one attempt rather than a unique-index error.
    """
    progress = await _claim_progress(db, user, module)
    existing = await open_attempt(db, user, module.translation_group_id)
    if existing is not None:
        return existing

    page_ids = {page["id"] for page in _snapshot_pages(version)}
    outstanding = page_ids - set(progress.pages_viewed)
    if outstanding:
        raise _conflict(
            "pages_outstanding",
            "Read every page of this module before taking the quiz.",
            pages_outstanding=len(outstanding),
            pages_total=len(page_ids),
        )
    if await best_counting_pass(db, user, module.translation_group_id, version) is not None:
        raise _conflict("quiz_already_passed", "You have already passed this quiz.")
    used = await attempts_used(db, user, module.translation_group_id, version.id)
    if quiz["max_attempts"] is not None and used >= quiz["max_attempts"]:
        raise _conflict(
            "attempts_exhausted",
            "You have used every attempt at this quiz. An Administrator can reset them.",
        )

    attempt = QuizAttempt(
        id=uuid.uuid4(),
        user_id=user.id,
        translation_group_id=module.translation_group_id,
        module_id=module.id,
        version_id=version.id,
        version_number=version.version_number,
        shuffle_seed=secrets.randbits(62),
        answers={},
    )
    db.add(attempt)
    await db.flush()
    return attempt


@router.get("", response_model=QuizState)
async def get_quiz_state(
    translation_group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> QuizState:
    """Where the learner stands: their open attempt, or the latest result."""
    reach = await _learner_reach(db, user)
    _, version = await _resolve_readable_variant(db, user, translation_group_id, reach)
    return await _state(db, user, translation_group_id, version, None)


@router.post("/attempts", response_model=QuizState)
async def start_or_resume_attempt(
    translation_group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> QuizState:
    module, version, quiz = await _resolve(db, user, translation_group_id)
    attempt = await _begin_attempt(db, user, module, version, quiz)
    await db.commit()
    return await _state(db, user, translation_group_id, version, attempt)


async def _owned_open_attempt(
    db: AsyncSession, user: User, group_id: uuid.UUID, attempt_id: uuid.UUID
) -> tuple[QuizAttempt, ModuleVersion, dict[str, Any]]:
    """The caller's own open attempt, locked for update.

    Someone else's attempt id, a missing one and one for another module are the
    same 404 — an attempt id is not something to be able to probe.
    """
    # Access to the material is checked too: a module withdrawn mid-attempt is
    # no longer available, attempt or not.
    reach = await _learner_reach(db, user)
    _, current = await _resolve_readable_variant(db, user, group_id, reach)
    attempt = await open_attempt(db, user, group_id, for_update=True)
    if attempt is None or attempt.id != attempt_id:
        submitted = await db.get(QuizAttempt, attempt_id)
        if submitted is not None and submitted.user_id == user.id and (
            submitted.translation_group_id == group_id
        ):
            raise _conflict("attempt_submitted", "This attempt has already been submitted.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    version = current if attempt.version_id == current.id else await db.get(
        ModuleVersion, attempt.version_id
    )
    quiz = snapshot_quiz(version) if version else None
    if version is None or quiz is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    return attempt, version, quiz


@router.put("/attempts/{attempt_id}/answers/{question_id}", response_model=QuizState)
async def save_answer(
    translation_group_id: uuid.UUID,
    attempt_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: AnswerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> QuizState:
    """Record (replace) the answer to one question. An empty list clears it."""
    attempt, version, quiz = await _owned_open_attempt(db, user, translation_group_id, attempt_id)
    question = next((q for q in quiz["questions"] if q["id"] == str(question_id)), None)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "question_not_found", "message": "That question is not in this quiz."},
        )
    chosen = list(dict.fromkeys(str(option_id) for option_id in payload.option_ids))
    valid = {o["id"] for o in question["options"]}
    if any(option_id not in valid for option_id in chosen):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_option", "message": "That option is not part of this question."},
        )
    if question["type"] != "multiple_choice" and len(chosen) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "too_many_options", "message": "Choose a single answer."},
        )
    # Reassigned, not mutated: SQLAlchemy does not see in-place JSONB changes.
    attempt.answers = {**attempt.answers, str(question_id): chosen}
    await db.commit()
    return await _state(db, user, translation_group_id, version, attempt)


@router.post("/attempts/{attempt_id}/submit", response_model=QuizState)
async def submit_attempt(
    translation_group_id: uuid.UUID,
    attempt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> QuizState:
    """Grade the stored answers. Graded against the attempt's own question set,
    so there is nothing in the request for a learner to forge."""
    attempt, _, quiz = await _owned_open_attempt(db, user, translation_group_id, attempt_id)
    if await submissions_in_window(db, user) >= SUBMIT_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "too_many_submissions",
                "message": "Too many quiz submissions. Wait a few minutes and try again.",
            },
        )
    result = grade(quiz, {qid: set(ids) for qid, ids in attempt.answers.items()})
    attempt.submitted_at = datetime.now(UTC)
    attempt.score_percent = result["score_percent"]
    attempt.correct_count = result["correct_count"]
    attempt.total_questions = result["total"]
    attempt.passed = result["passed"]
    attempt.question_results = {r["question_id"]: r["correct"] for r in result["questions"]}
    await db.commit()
    reach = await _learner_reach(db, user)
    _, current = await _resolve_readable_variant(db, user, translation_group_id, reach)
    return await _state(db, user, translation_group_id, current, attempt)


@router.post("/retake", response_model=QuizState)
async def retake(
    translation_group_id: uuid.UUID,
    payload: RetakeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> QuizState:
    """After a failure, an explicit choice: retake only the quiz, or the module.

    Both are requests, not side effects of failing — the server never decides
    for a learner that they must re-read. `quiz` keeps `pages_viewed`; `module`
    clears it, so the attestation's pages check is a real gate again.
    """
    module, version, quiz = await _resolve(db, user, translation_group_id)
    progress = await _claim_progress(db, user, module)
    if await open_attempt(db, user, translation_group_id) is not None:
        raise _conflict("attempt_in_progress", "Finish or submit your current attempt first.")
    last = await latest_submitted(db, user, translation_group_id, version.id)
    if last is None or last.passed or (
        await best_counting_pass(db, user, translation_group_id, version) is not None
    ):
        raise _conflict("nothing_to_retake", "There is no failed attempt to retake.")

    if payload.mode == "module":
        if quiz["max_attempts"] is not None and (
            await attempts_used(db, user, translation_group_id, version.id) >= quiz["max_attempts"]
        ):
            # Re-reading would buy nothing: there is no attempt left to use it on.
            raise _conflict(
                "attempts_exhausted",
                "You have used every attempt at this quiz. An Administrator can reset them.",
            )
        _clear_page_progress(progress)
        await db.commit()
        return await _state(db, user, translation_group_id, version, None)

    attempt = await _begin_attempt(db, user, module, version, quiz)
    await db.commit()
    return await _state(db, user, translation_group_id, version, attempt)


def _clear_page_progress(progress: ModuleProgress) -> None:
    progress.pages_viewed = []
    progress.current_page_id = None

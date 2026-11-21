"""Learner-side quiz rules: building what a learner sees, counting attempts, and
deciding which pass counts.

Grading itself stays in `app.quiz.grade`; this module wraps it with the parts
that only exist once a *person* is taking the quiz. Everything is computed from
the attempt's own frozen version snapshot, never the draft and never the
module's current version — a learner finishes the quiz they started.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, ModuleVersion, QuizAttempt, User
from app.quiz import comparable
from app.schemas.quiz_taking import (
    AttemptOption,
    AttemptQuestion,
    AttemptResult,
    AttemptView,
    LearnerQuizSummary,
    QuestionOutcome,
    RevealedAnswer,
)

# Submissions per learner in the window. Not per quiz: guessing the key of two
# quizzes in parallel is no harder than one.
SUBMIT_LIMIT = 5
SUBMIT_WINDOW = timedelta(minutes=10)


def snapshot_quiz(version: ModuleVersion) -> dict[str, Any] | None:
    quiz = version.snapshot.get("quiz")
    return quiz if quiz else None


def ordered_questions(quiz: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    """The quiz's questions, options included, in this attempt's order.

    Seeded, so a reload — or a review of a finished attempt — reproduces the
    order the learner saw. True/false options keep their order: "False, True"
    would only be confusing.
    """
    rng = random.Random(seed)
    questions = []
    for question in sorted(quiz["questions"], key=lambda q: q["position"]):
        options = sorted(question["options"], key=lambda o: o["position"])
        if quiz["shuffle"] and question["type"] != "true_false":
            rng.shuffle(options)
        questions.append({**question, "options": options})
    if quiz["shuffle"]:
        rng.shuffle(questions)
    return questions


def attempt_view(attempt: QuizAttempt, quiz: dict[str, Any]) -> AttemptView:
    ordered = ordered_questions(quiz, attempt.shuffle_seed)
    questions = [
        AttemptQuestion(
            id=uuid.UUID(q["id"]),
            type=q["type"],
            schema_version=q["schema_version"],
            prompt=q["prompt"],
            options=[AttemptOption(id=uuid.UUID(o["id"]), text=o["text"]) for o in q["options"]],
        )
        for q in ordered
    ]
    result = None
    if attempt.submitted_at is not None and attempt.question_results is not None:
        revealed = None
        if attempt.passed and quiz["reveal_after_pass"]:
            revealed = [
                RevealedAnswer(
                    question_id=uuid.UUID(q["id"]),
                    correct_option_ids=[
                        uuid.UUID(o["id"]) for o in q["options"] if o["is_correct"]
                    ],
                    explanation=q["explanation"],
                )
                for q in ordered
            ]
        result = AttemptResult(
            score_percent=attempt.score_percent or 0,
            correct_count=attempt.correct_count or 0,
            total=attempt.total_questions or 0,
            pass_mark_percent=quiz["pass_mark_percent"],
            passed=bool(attempt.passed),
            questions=[
                QuestionOutcome(
                    question_id=uuid.UUID(q["id"]),
                    correct=bool(attempt.question_results.get(q["id"])),
                )
                for q in ordered
            ],
            revealed=revealed,
        )
    return AttemptView(
        id=attempt.id,
        version_number=attempt.version_number,
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
        questions=questions,
        answers={
            uuid.UUID(question_id): [uuid.UUID(option_id) for option_id in option_ids]
            for question_id, option_ids in attempt.answers.items()
        },
        result=result,
    )


async def open_attempt(
    db: AsyncSession, user: User, group_id: uuid.UUID, *, for_update: bool = False
) -> QuizAttempt | None:
    statement = select(QuizAttempt).where(
        QuizAttempt.user_id == user.id,
        QuizAttempt.translation_group_id == group_id,
        QuizAttempt.submitted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def group_version_ids(
    db: AsyncSession, group_id: uuid.UUID, version_id: uuid.UUID | None = None
) -> set[uuid.UUID]:
    """The versions currently live across every language variant of a material.

    The cap and "any prior pass" are about the *material*, not one language: a
    learner who burns their attempts in German and switches to English has not
    got fresh ones. Each variant's own current version is in; an earlier version
    of any variant is out, so a republish still starts the count afresh.
    """
    ids = set(
        (
            await db.execute(
                select(Module.current_version_id).where(
                    Module.translation_group_id == group_id,
                    Module.current_version_id.is_not(None),
                    Module.status != "deleted",
                )
            )
        ).scalars()
    )
    if version_id is not None:
        ids.add(version_id)
    return ids


async def attempts_used(
    db: AsyncSession, user: User, group_id: uuid.UUID, version_id: uuid.UUID
) -> int:
    """Attempts against this material's live versions, across its translations.

    A republish starts the count afresh; a language switch does not.
    """
    return (
        await db.scalar(
            select(func.count()).where(
                QuizAttempt.user_id == user.id,
                QuizAttempt.translation_group_id == group_id,
                QuizAttempt.version_id.in_(await group_version_ids(db, group_id, version_id)),
            )
        )
        or 0
    )


async def latest_submitted(
    db: AsyncSession, user: User, group_id: uuid.UUID, version_id: uuid.UUID | None = None
) -> QuizAttempt | None:
    statement = (
        select(QuizAttempt)
        .where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.translation_group_id == group_id,
            QuizAttempt.submitted_at.is_not(None),
        )
        .order_by(QuizAttempt.submitted_at.desc())
        .limit(1)
    )
    if version_id is not None:
        statement = statement.where(
            QuizAttempt.version_id.in_(await group_version_ids(db, group_id, version_id))
        )
    return (await db.execute(statement)).scalar_one_or_none()


async def best_counting_pass(
    db: AsyncSession, user: User, group_id: uuid.UUID, current: ModuleVersion
) -> QuizAttempt | None:
    """The highest-scoring passing attempt that counts for `current`'s quiz.

    An attempt counts if it was taken on `current` itself, or on an earlier
    version whose quiz is identical in content — so a minor republish does not
    send everyone back to a quiz that did not change, while a changed quiz
    makes the old pass stop counting.
    """
    current_quiz = snapshot_quiz(current)
    if current_quiz is None:
        return None
    passes = (
        await db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.user_id == user.id,
                QuizAttempt.translation_group_id == group_id,
                QuizAttempt.passed.is_(True),
            )
            .order_by(QuizAttempt.score_percent.desc(), QuizAttempt.submitted_at.desc())
        )
    ).scalars()
    # Every variant's live version counts: a pass in one language survives a
    # switch to another. Earlier versions still need an identical quiz.
    same_content: dict[uuid.UUID, bool] = {
        vid: True for vid in await group_version_ids(db, group_id, current.id)
    }
    for attempt in passes:
        if attempt.version_id not in same_content:
            other = await db.get(ModuleVersion, attempt.version_id)
            other_quiz = snapshot_quiz(other) if other else None
            same_content[attempt.version_id] = other_quiz is not None and comparable(
                other_quiz
            ) == comparable(current_quiz)
        if same_content[attempt.version_id]:
            return attempt
    return None


async def quiz_summary(
    db: AsyncSession, user: User, group_id: uuid.UUID, version: ModuleVersion
) -> LearnerQuizSummary | None:
    quiz = snapshot_quiz(version)
    if quiz is None:
        return None
    used = await attempts_used(db, user, group_id, version.id)
    cap = quiz["max_attempts"]
    winner = await best_counting_pass(db, user, group_id, version)
    best = await db.scalar(
        select(func.max(QuizAttempt.score_percent)).where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.translation_group_id == group_id,
            QuizAttempt.version_id.in_(await group_version_ids(db, group_id, version.id)),
        )
    )
    return LearnerQuizSummary(
        question_count=len(quiz["questions"]),
        pass_mark_percent=quiz["pass_mark_percent"],
        max_attempts=cap,
        attempts_used=used,
        attempts_remaining=None if cap is None else max(cap - used, 0),
        exhausted=cap is not None and used >= cap and winner is None,
        passed=winner is not None,
        best_score_percent=winner.score_percent if winner else best,
    )


async def submissions_in_window(db: AsyncSession, user: User) -> int:
    since = datetime.now(UTC) - SUBMIT_WINDOW
    return (
        await db.scalar(
            select(func.count()).where(
                QuizAttempt.user_id == user.id, QuizAttempt.submitted_at >= since
            )
        )
        or 0
    )


async def reset_attempts(db: AsyncSession, user_id: uuid.UUID, group_id: uuid.UUID) -> int:
    """Delete every attempt a learner has on a material, in all its languages."""
    result = await db.execute(
        delete(QuizAttempt).where(
            QuizAttempt.user_id == user_id, QuizAttempt.translation_group_id == group_id
        )
    )
    return result.rowcount or 0


async def deidentify_attempts(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Right to erasure for a learner's quiz attempts.

    An attempt in progress is deleted outright — it is nothing but answers. A
    submitted one keeps only what a statistic needs (score, pass/fail, version,
    timestamp and the per-question right/wrong flags), with the answers
    themselves hard-deleted. The attempt row stays against the user's tombstone,
    which carries no name or email, so it identifies no one.
    """
    await db.execute(
        delete(QuizAttempt).where(
            QuizAttempt.user_id == user_id, QuizAttempt.submitted_at.is_(None)
        )
    )
    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.user_id == user_id)
        .values(answers={}, shuffle_seed=0)
    )


async def attempt_aggregates(db: AsyncSession, group_id: uuid.UUID) -> dict[str, Any]:
    """Submitted-attempt statistics for a material, erased learners included.

    Counts every submitted attempt whoever made it: an erase removes the
    identity from an attempt, never the attempt from the figures.
    """
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(QuizAttempt.passed.is_(True)),
                func.avg(QuizAttempt.score_percent),
            ).where(
                QuizAttempt.translation_group_id == group_id,
                QuizAttempt.submitted_at.is_not(None),
            )
        )
    ).one()
    return {
        "attempts": row[0],
        "passed": row[1],
        "average_score_percent": float(row[2]) if row[2] is not None else None,
    }

"""Quiz rules that do not belong to any one route.

Three jobs, shared by authoring now and by learner attempts (ticket 9) later:

* `serialize_quiz` turns the draft rows into the plain structure that is frozen
  into a version snapshot, and that `quiz_problems` and `grade` both read — so a
  draft, a snapshot and an author try-out can never disagree about what a quiz
  *is*.
* `quiz_problems` is the publish gate.
* `grade` is the one place a set of answers becomes a score. The server grades
  everything; a client never learns correctness from anything but this.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import extract_search_text
from app.models import ModuleQuiz, QuizOption, QuizQuestion

QuestionType = Literal["single_choice", "multiple_choice", "true_false"]
TRUE_FALSE_OPTIONS = ("true", "false")

QuizChange = Literal["none", "added", "changed", "removed"]


async def load_draft_quiz(
    db: AsyncSession, module_id: uuid.UUID
) -> tuple[ModuleQuiz, list[tuple[QuizQuestion, list[QuizOption]]]] | None:
    quiz = (
        await db.execute(select(ModuleQuiz).where(ModuleQuiz.module_id == module_id))
    ).scalar_one_or_none()
    if quiz is None:
        return None
    questions = list(
        (
            await db.execute(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_id == quiz.id)
                .order_by(QuizQuestion.position)
            )
        ).scalars()
    )
    options_by_question: dict[uuid.UUID, list[QuizOption]] = {q.id: [] for q in questions}
    if questions:
        rows = (
            await db.execute(
                select(QuizOption)
                .where(QuizOption.question_id.in_(options_by_question))
                .order_by(QuizOption.position)
            )
        ).scalars()
        for option in rows:
            options_by_question[option.question_id].append(option)
    return quiz, [(q, options_by_question[q.id]) for q in questions]


def serialize_quiz(
    quiz: ModuleQuiz, questions: list[tuple[QuizQuestion, list[QuizOption]]]
) -> dict[str, Any]:
    """The plain-dict form of a quiz: what a snapshot stores and grading reads.

    Contains correctness data, so it is for server-side use and authors only —
    ticket 9's learner payloads are built from it with that data removed.
    """
    return {
        "pass_mark_percent": quiz.pass_mark_percent,
        "max_attempts": quiz.max_attempts,
        "shuffle": quiz.shuffle,
        "reveal_after_pass": quiz.reveal_after_pass,
        "questions": [
            {
                "id": str(question.id),
                "position": question.position,
                "type": question.type,
                "schema_version": question.schema_version,
                "prompt": question.prompt,
                "explanation": question.explanation,
                "options": [
                    {
                        "id": str(option.id),
                        "position": option.position,
                        "text": option.text,
                        "is_correct": option.is_correct,
                    }
                    for option in options
                ],
            }
            for question, options in questions
        ],
    }


def comparable(quiz: dict[str, Any] | None) -> dict[str, Any] | None:
    """A quiz with its identities stripped, for "did the content change?".

    Row ids differ between a draft and the snapshot taken from it only if the
    author deleted and recreated something; what matters to a learner is what
    they would be asked, so equality is judged on content alone.
    """
    if quiz is None:
        return None
    return {
        "pass_mark_percent": quiz["pass_mark_percent"],
        "max_attempts": quiz["max_attempts"],
        "shuffle": quiz["shuffle"],
        "reveal_after_pass": quiz["reveal_after_pass"],
        "questions": [
            {
                "type": q["type"],
                "prompt": q["prompt"],
                "explanation": q["explanation"],
                "options": [
                    {"text": o["text"], "is_correct": o["is_correct"]} for o in q["options"]
                ],
            }
            for q in quiz["questions"]
        ],
    }


def classify_change(published: dict[str, Any] | None, draft: dict[str, Any] | None) -> QuizChange:
    """How the draft's quiz differs from the last published one."""
    if published is None and draft is None:
        return "none"
    if published is None:
        return "added"
    if draft is None:
        return "removed"
    return "none" if comparable(published) == comparable(draft) else "changed"


def quiz_problems(quiz: dict[str, Any]) -> list[dict[str, str | None]]:
    """Everything that stops this quiz being published, or an empty list."""
    problems: list[dict[str, str | None]] = []

    def add(code: str, message: str, question_id: str | None = None) -> None:
        problems.append({"code": code, "message": message, "question_id": question_id})

    questions = quiz["questions"]
    if not questions:
        add("no_questions", "A quiz needs at least one question.")
    for number, question in enumerate(questions, start=1):
        qid = question["id"]
        label = f"Question {number}"
        if not extract_search_text(question["prompt"]).strip():
            add("empty_prompt", f"{label} has no question text.", qid)
        options = question["options"]
        texts = [o["text"].strip() for o in options]
        correct = sum(1 for o in options if o["is_correct"])
        if question["type"] == "true_false":
            if sorted(texts) != sorted(TRUE_FALSE_OPTIONS):
                add("bad_true_false", f"{label} must offer exactly True and False.", qid)
            if correct != 1:
                add("correct_answer_count", f"{label} needs exactly one correct answer.", qid)
            continue
        if len(options) < 2:
            add("too_few_options", f"{label} needs at least two answer options.", qid)
        if any(not text for text in texts):
            add("empty_option", f"{label} has an empty answer option.", qid)
        non_empty = [text.casefold() for text in texts if text]
        if len(set(non_empty)) != len(non_empty):
            add("duplicate_options", f"{label} has duplicate answer options.", qid)
        if question["type"] == "single_choice" and correct != 1:
            add("correct_answer_count", f"{label} needs exactly one correct answer.", qid)
        elif question["type"] == "multiple_choice" and correct < 1:
            add("correct_answer_count", f"{label} needs at least one correct answer.", qid)
    return problems


def grade(quiz: dict[str, Any], answers: dict[str, set[str]]) -> dict[str, Any]:
    """Grade `answers` (question id → chosen option ids) against `quiz`.

    All-or-nothing per question on the exact set of correct options, so a
    multiple-choice answer that is a strict subset or superset scores zero.
    An unanswered question is a wrong one.
    """
    results = []
    for question in quiz["questions"]:
        correct_ids = {o["id"] for o in question["options"] if o["is_correct"]}
        chosen = answers.get(question["id"], set())
        results.append(
            {
                "question_id": question["id"],
                "correct": bool(chosen) and chosen == correct_ids,
                "correct_option_ids": sorted(correct_ids),
            }
        )
    total = len(results)
    correct_count = sum(1 for r in results if r["correct"])
    score = round(100 * correct_count / total) if total else 0
    return {
        "correct_count": correct_count,
        "total": total,
        "score_percent": score,
        "passed": total > 0 and score >= quiz["pass_mark_percent"],
        "questions": results,
    }

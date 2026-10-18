"""Quiz authoring: the draft quiz on a module, its questions, and the try-out.

Everything here edits the *draft*. Publishing (`app.routes.content`) validates
it and freezes a copy into the immutable version snapshot; nothing in this file
can reach a published version.

Question prompts and explanations go through `validate_page_body` — the same
check page bodies get — so a prompt is rejected, never stripped, on anything
the schema does not allow.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import ensure_module_editable
from app.db import get_db
from app.dependencies import get_module_or_404, require_content_manager
from app.models import Module, ModuleQuiz, QuizOption, QuizQuestion, User
from app.quiz import grade, load_draft_quiz, quiz_problems, serialize_quiz
from app.routes.content import validate_page_body
from app.schemas.quiz import (
    MAX_QUESTIONS_PER_QUIZ,
    OptionInput,
    QuestionCreateRequest,
    QuestionReorderRequest,
    QuestionUpdateRequest,
    QuizResponse,
    QuizSettingsRequest,
    TryoutRequest,
    TryoutResponse,
)
from app.security.audit import record_audit_log

router = APIRouter(prefix="/api/content", tags=["quiz"])


def _quiz_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "no_quiz", "message": "This module has no quiz."},
    )


async def _response(db: AsyncSession, module_id: uuid.UUID) -> QuizResponse | None:
    loaded = await load_draft_quiz(db, module_id)
    if loaded is None:
        return None
    serialized = serialize_quiz(*loaded)
    return QuizResponse(**serialized, problems=quiz_problems(serialized))  # type: ignore[arg-type]


async def _require_quiz(db: AsyncSession, module: Module) -> ModuleQuiz:
    quiz = (
        await db.execute(select(ModuleQuiz).where(ModuleQuiz.module_id == module.id))
    ).scalar_one_or_none()
    if quiz is None:
        raise _quiz_not_found()
    return quiz


async def _question_or_404(db: AsyncSession, quiz: ModuleQuiz, question_id: uuid.UUID) -> QuizQuestion:
    question = (
        await db.execute(
            select(QuizQuestion).where(
                QuizQuestion.id == question_id, QuizQuestion.quiz_id == quiz.id
            )
        )
    ).scalar_one_or_none()
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "no_question", "message": "Question not found."},
        )
    return question


def _validated_rich_text(value: dict[str, Any], schema_version: int) -> dict[str, Any]:
    document, _ = validate_page_body(value, schema_version)
    return document


def _add_options(db: AsyncSession, question: QuizQuestion, options: list[OptionInput]) -> None:
    for position, option in enumerate(options):
        db.add(
            QuizOption(
                question_id=question.id,
                position=position,
                text=option.text.strip(),
                is_correct=option.is_correct,
            )
        )


async def _audit(
    db: AsyncSession, author: User, module: Module, change: str, **extra: Any
) -> None:
    module.last_edited_by = author.id
    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="quiz_updated",
        detail={"module_id": str(module.id), "title": module.title, "change": change, **extra},
    )


@router.get("/modules/{module_id}/quiz", response_model=QuizResponse | None)
async def get_quiz(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> QuizResponse | None:
    """The draft quiz with its correct answers, or `null` if the module has none."""
    module = await get_module_or_404(db, module_id)
    return await _response(db, module.id)


@router.put("/modules/{module_id}/quiz", response_model=QuizResponse)
async def put_quiz(
    module_id: uuid.UUID,
    payload: QuizSettingsRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> QuizResponse:
    """Create the quiz or replace its settings; questions are untouched."""
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
    quiz = (
        await db.execute(select(ModuleQuiz).where(ModuleQuiz.module_id == module.id))
    ).scalar_one_or_none()
    created = quiz is None
    if quiz is None:
        quiz = ModuleQuiz(module_id=module.id)
        db.add(quiz)
    quiz.pass_mark_percent = payload.pass_mark_percent
    quiz.max_attempts = payload.max_attempts
    quiz.shuffle = payload.shuffle
    quiz.reveal_after_pass = payload.reveal_after_pass
    await db.flush()
    await _audit(db, author, module, "created" if created else "settings_updated")
    await db.commit()
    response = await _response(db, module.id)
    assert response is not None
    return response


@router.delete("/modules/{module_id}/quiz", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> Response:
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
    quiz = await _require_quiz(db, module)
    await db.delete(quiz)
    await db.flush()
    await _audit(db, author, module, "removed")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/modules/{module_id}/quiz/questions",
    response_model=QuizResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    module_id: uuid.UUID,
    payload: QuestionCreateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> QuizResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
    quiz = await _require_quiz(db, module)

    existing = list(
        (
            await db.execute(select(QuizQuestion.id).where(QuizQuestion.quiz_id == quiz.id))
        ).scalars()
    )
    if len(existing) >= MAX_QUESTIONS_PER_QUIZ:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "too_many_questions",
                "message": f"A quiz may have at most {MAX_QUESTIONS_PER_QUIZ} questions.",
            },
        )
    prompt = _validated_rich_text(payload.prompt, payload.schema_version)
    explanation = (
        _validated_rich_text(payload.explanation, payload.schema_version)
        if payload.explanation is not None
        else None
    )
    question = QuizQuestion(
        quiz_id=quiz.id,
        position=len(existing),
        type=payload.type,
        prompt=prompt,
        explanation=explanation,
        schema_version=payload.schema_version,
    )
    db.add(question)
    await db.flush()
    _add_options(db, question, payload.options)
    await db.flush()
    await _audit(db, author, module, "question_added", question_id=str(question.id))
    await db.commit()
    response = await _response(db, module.id)
    assert response is not None
    return response


@router.patch("/modules/{module_id}/quiz/questions/{question_id}", response_model=QuizResponse)
async def update_question(
    module_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: QuestionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> QuizResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
    quiz = await _require_quiz(db, module)
    question = await _question_or_404(db, quiz, question_id)

    fields = payload.model_fields_set
    version = payload.schema_version if payload.schema_version is not None else question.schema_version
    if ("prompt" in fields or "explanation" in fields) and payload.schema_version is None:
        # Rich text is only meaningful against a stated schema version.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "schema_version_required",
                "message": "schema_version is required when changing a prompt or explanation.",
            },
        )
    if "prompt" in fields:
        if payload.prompt is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "prompt_required", "message": "A prompt is required."},
            )
        question.prompt = _validated_rich_text(payload.prompt, version)
    if "explanation" in fields:
        question.explanation = (
            _validated_rich_text(payload.explanation, version)
            if payload.explanation is not None
            else None
        )
    if "prompt" in fields or "explanation" in fields:
        question.schema_version = version
    if payload.type is not None:
        question.type = payload.type
    if payload.options is not None:
        await db.execute(delete(QuizOption).where(QuizOption.question_id == question.id))
        await db.flush()
        _add_options(db, question, payload.options)
    await db.flush()
    await _audit(db, author, module, "question_updated", question_id=str(question.id))
    await db.commit()
    response = await _response(db, module.id)
    assert response is not None
    return response


@router.delete("/modules/{module_id}/quiz/questions/{question_id}", response_model=QuizResponse)
async def delete_question(
    module_id: uuid.UUID,
    question_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> QuizResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
    quiz = await _require_quiz(db, module)
    question = await _question_or_404(db, quiz, question_id)
    await db.delete(question)
    await db.flush()
    remaining = (
        await db.execute(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id).order_by(QuizQuestion.position)
        )
    ).scalars()
    for position, other in enumerate(remaining):
        other.position = position
    await _audit(db, author, module, "question_removed", question_id=str(question_id))
    await db.commit()
    response = await _response(db, module.id)
    assert response is not None
    return response


@router.post("/modules/{module_id}/quiz/questions/reorder", response_model=QuizResponse)
async def reorder_questions(
    module_id: uuid.UUID,
    payload: QuestionReorderRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> QuizResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
    quiz = await _require_quiz(db, module)
    questions = {
        q.id: q
        for q in (
            await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
        ).scalars()
    }
    if len(payload.question_ids) != len(set(payload.question_ids)) or set(
        payload.question_ids
    ) != set(questions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "reorder_mismatch",
                "message": "The new order must list every question of the quiz exactly once.",
            },
        )
    for position, question_id in enumerate(payload.question_ids):
        questions[question_id].position = position
    await db.flush()
    await _audit(db, author, module, "questions_reordered")
    await db.commit()
    response = await _response(db, module.id)
    assert response is not None
    return response


@router.post("/modules/{module_id}/quiz/tryout", response_model=TryoutResponse)
async def tryout_quiz(
    module_id: uuid.UUID,
    payload: TryoutRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> TryoutResponse:
    """Grade an author's answers against the draft, recording nothing.

    No attempt row, no progress, no audit entry: a try-out is a read in the
    shape of a write, so an author can see the learner experience (and the
    grading) without leaving a trace in anyone's record.
    """
    module = await get_module_or_404(db, module_id)
    loaded = await load_draft_quiz(db, module.id)
    if loaded is None:
        raise _quiz_not_found()
    quiz = serialize_quiz(*loaded)
    if not quiz["questions"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_questions", "message": "Add a question before trying the quiz."},
        )
    options_by_question = {
        q["id"]: {o["id"] for o in q["options"]} for q in quiz["questions"]
    }
    answers: dict[str, set[str]] = {}
    for question_id, option_ids in payload.answers.items():
        chosen = {str(option_id) for option_id in option_ids}
        if str(question_id) not in options_by_question or not chosen <= options_by_question[
            str(question_id)
        ]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "unknown_answer",
                    "message": "An answer names a question or option that is not in this quiz.",
                },
            )
        answers[str(question_id)] = chosen
    result = grade(quiz, answers)
    return TryoutResponse(pass_mark_percent=quiz["pass_mark_percent"], **result)

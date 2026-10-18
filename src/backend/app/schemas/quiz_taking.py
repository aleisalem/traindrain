"""What a learner sends and receives while taking a quiz.

The one rule of this file: nothing here can carry correctness data except
`RevealedAnswer`, which is populated only after a pass and only when the author
enabled it. There is deliberately no `is_correct` anywhere, and an option is just
an id and its text.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.quiz import QuestionType


class LearnerQuizSummary(BaseModel):
    question_count: int
    pass_mark_percent: int
    max_attempts: int | None
    attempts_used: int
    # None when the cap is absent.
    attempts_remaining: int | None
    exhausted: bool
    # A passing attempt exists that counts towards the version being read.
    passed: bool
    best_score_percent: int | None


class AttemptOption(BaseModel):
    id: uuid.UUID
    text: str


class AttemptQuestion(BaseModel):
    id: uuid.UUID
    type: QuestionType
    schema_version: int
    prompt: dict[str, Any]
    options: list[AttemptOption]


class QuestionOutcome(BaseModel):
    question_id: uuid.UUID
    correct: bool


class RevealedAnswer(BaseModel):
    question_id: uuid.UUID
    correct_option_ids: list[uuid.UUID]
    explanation: dict[str, Any] | None


class AttemptResult(BaseModel):
    score_percent: int
    correct_count: int
    total: int
    pass_mark_percent: int
    passed: bool
    questions: list[QuestionOutcome]
    # Only after a pass, and only if the author allowed it.
    revealed: list[RevealedAnswer] | None


class AttemptView(BaseModel):
    id: uuid.UUID
    version_number: int
    started_at: datetime
    submitted_at: datetime | None
    # In this attempt's own shuffled order.
    questions: list[AttemptQuestion]
    answers: dict[uuid.UUID, list[uuid.UUID]]
    result: AttemptResult | None


class QuizState(BaseModel):
    summary: LearnerQuizSummary
    # The open attempt if there is one, otherwise the latest submitted one.
    attempt: AttemptView | None


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_ids: list[uuid.UUID] = Field(max_length=20)


class RetakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # quiz: straight back to a fresh attempt, page progress kept.
    # module: page progress cleared so the pages must be read again.
    mode: Literal["quiz", "module"]

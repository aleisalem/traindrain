import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionType = Literal["single_choice", "multiple_choice", "true_false"]

MAX_QUESTIONS_PER_QUIZ = 100
MAX_OPTIONS_PER_QUESTION = 10


class QuizSettingsRequest(BaseModel):
    """A quiz's settings. `PUT` replaces them wholesale, creating the quiz if absent."""

    model_config = ConfigDict(extra="forbid")

    pass_mark_percent: int = Field(default=80, ge=1, le=100)
    # None means unlimited.
    max_attempts: int | None = Field(default=None, ge=1, le=100)
    shuffle: bool = False
    reveal_after_pass: bool = False


class OptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An empty draft option is allowed — the publish gate is what refuses it.
    text: str = Field(max_length=500)
    is_correct: bool = False


class QuestionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: QuestionType
    schema_version: int
    prompt: dict[str, Any]
    explanation: dict[str, Any] | None = None
    options: list[OptionInput] = Field(max_length=MAX_OPTIONS_PER_QUESTION)


class QuestionUpdateRequest(BaseModel):
    """Every field optional; `options`, when present, replaces the whole list."""

    model_config = ConfigDict(extra="forbid")

    type: QuestionType | None = None
    schema_version: int | None = None
    prompt: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    options: list[OptionInput] | None = Field(default=None, max_length=MAX_OPTIONS_PER_QUESTION)


class QuestionReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_ids: list[uuid.UUID]


class OptionResponse(BaseModel):
    id: uuid.UUID
    position: int
    text: str
    # Author-facing only: this schema is never used on a learner route.
    is_correct: bool


class QuestionResponse(BaseModel):
    id: uuid.UUID
    position: int
    type: QuestionType
    schema_version: int
    prompt: dict[str, Any]
    explanation: dict[str, Any] | None
    options: list[OptionResponse]


class QuizProblem(BaseModel):
    code: str
    message: str
    question_id: str | None = None


class QuizResponse(BaseModel):
    pass_mark_percent: int
    max_attempts: int | None
    shuffle: bool
    reveal_after_pass: bool
    questions: list[QuestionResponse]
    # What would stop this quiz being published right now.
    problems: list[QuizProblem]


class TryoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # question id → the option ids chosen. An unanswered question is omitted.
    answers: dict[uuid.UUID, list[uuid.UUID]] = Field(default_factory=dict)


class TryoutQuestionResult(BaseModel):
    question_id: uuid.UUID
    correct: bool
    correct_option_ids: list[uuid.UUID]


class TryoutResponse(BaseModel):
    score_percent: int
    correct_count: int
    total: int
    pass_mark_percent: int
    passed: bool
    questions: list[TryoutQuestionResult]

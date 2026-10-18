import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModuleQuiz(Base):
    """The working draft of a module's quiz.

    One per module row — each language variant carries its own quiz (ticket 10)
    — and, like `module_pages`, always the *draft*: learners are graded against
    the copy frozen into `module_versions.snapshot["quiz"]` at publish time, so
    editing this never changes a published version.
    """

    __tablename__ = "module_quizzes"
    __table_args__ = (
        CheckConstraint(
            "pass_mark_percent between 1 and 100", name="ck_module_quizzes_pass_mark"
        ),
        CheckConstraint(
            "max_attempts is null or max_attempts >= 1", name="ck_module_quizzes_max_attempts"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    pass_mark_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    # None means unlimited.
    max_attempts: Mapped[int | None] = mapped_column(Integer)
    shuffle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reveal_after_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position", deferrable=True, initially="DEFERRED"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("module_quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # The discriminator: single_choice | multiple_choice | true_false today,
    # with room for other question types without a table per type.
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Validated ProseMirror trees (see `app.content.validation`), never HTML.
    prompt: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuizOption(Base):
    __tablename__ = "quiz_options"
    __table_args__ = (
        UniqueConstraint("question_id", "position", deferrable=True, initially="DEFERRED"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quiz_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Plain text. For true_false the text is the literal "true" / "false" so the
    # UI can localize the label rather than the server picking a language.
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class QuizAttempt(Base):
    """One learner's go at one version's quiz.

    In progress until `submitted_at` is set; at most one open attempt per learner
    and material (partial unique index), which is what makes "resume after
    closing the tab" unambiguous. Everything needed to reproduce what the
    learner saw is stored: the version, and the shuffle seed that fixes question
    and option order. `answers` is question id -> chosen option ids, validated
    on write against the attempt's own version, never the current one.
    """

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        Index("ix_quiz_attempts_learner", "user_id", "translation_group_id"),
        Index(
            "uq_quiz_attempts_one_open",
            "user_id",
            "translation_group_id",
            unique=True,
            postgresql_where="submitted_at is null",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    translation_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("module_translation_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_versions.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    shuffle_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    answers: Mapped[dict[str, list[str]]] = mapped_column(JSONB, nullable=False, default=dict)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score_percent: Mapped[int | None] = mapped_column(Integer)
    correct_count: Mapped[int | None] = mapped_column(Integer)
    total_questions: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    # question id -> bool. Never the correct option ids: those live only in the
    # version snapshot and leave the server only through `reveal`.
    question_results: Mapped[dict[str, bool] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

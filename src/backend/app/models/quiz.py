import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

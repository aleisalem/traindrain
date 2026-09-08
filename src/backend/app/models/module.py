import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModuleTranslationGroup(Base):
    """The body of material a set of language variants share.

    Every module belongs to exactly one group, and a standalone module gets a
    group of its own on creation. Assignments (Release 1, ticket 7) target a
    group rather than a module, so adding a translation later never requires
    rewriting an existing assignment.
    """

    __tablename__ = "module_translation_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable and use_alter: the group row is written before the module that
    # will be its primary exists, and the two tables reference each other, so
    # this constraint has to be added after both tables are created.
    primary_module_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", use_alter=True, name="fk_translation_group_primary_module"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Module(Base):
    """One language variant of a piece of learning material."""

    __tablename__ = "modules"
    __table_args__ = (UniqueConstraint("translation_group_id", "language"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    translation_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_translation_groups.id"), nullable=False, index=True
    )
    # Immutable after creation — the full-text search configuration for a
    # module's pages is derived from this value at write time (ticket 2), so a
    # language change would silently leave the stored index stemmed for the
    # wrong language. A different language is a new variant, not an edit.
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    catalog_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # draft | published | deleted — `deleted` is terminal.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Optimistic-lock token for draft mutations, so two Content Managers
    # editing the same draft get a conflict rather than a lost edit.
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # There is no module ownership — any Content Manager may edit any module —
    # but these record who did what, alongside the audit log.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    last_edited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

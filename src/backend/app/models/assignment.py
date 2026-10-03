import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Assignment(Base):
    """Who has to read a body of material, and by when.

    Targets a translation group, never a bare module, so a translation added
    later is automatically covered by an assignment made before it existed.

    `target_id` is deliberately not a foreign key: it names a row in `groups`
    or in `users` depending on `target_type`, and a polymorphic reference
    cannot be declared as one constraint. Existence is checked in the route
    at creation time instead.

    Membership is **not** expanded into rows here — a group assignment stays
    one row naming the group, and a learner's list is computed against their
    *current* group memberships at read time (`app.assignments`). That is what
    makes a later group joiner inherit the assignment automatically, and a
    leaver keep only the progress they already earned.
    """

    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint("target_type in ('user', 'group')", name="ck_assignments_target_type"),
        CheckConstraint(
            "requirement in ('mandatory', 'recommended')", name="ck_assignments_requirement"
        ),
        # One assignment per (material, target) pair — a second attempt to
        # assign the same group or person again is a conflict, not a second
        # round of emails.
        UniqueConstraint(
            "translation_group_id", "target_type", "target_id", name="uq_assignments_target"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    translation_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("module_translation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # user | group
    target_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    # mandatory | recommended
    requirement: Mapped[str] = mapped_column(String(20), nullable=False)
    auto_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Campaign(Base):
    """A programme of modules aimed at groups (and, for Administrators, people).

    A campaign never copies anything into `assignments`: what a learner may
    read through one is derived live from `campaign_targets` against their
    current group membership, the way Release 1 derives it from assignments.
    Drafts are invisible to learners and send nothing — every learner-facing
    rule arrives with the lifecycle in later tickets, keyed on `status`.
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "status in ('draft', 'active', 'suspended', 'closed')", name="ck_campaigns_status"
        ),
        CheckConstraint(
            "start_date is null or due_date is null or due_date >= start_date",
            name="ck_campaigns_dates_ordered",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # draft | active | suspended | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    sequential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    # Set when a campaign is resumed after its due date has passed; cleared the
    # moment an author sets a date that is not in the past. Stored (not derived)
    # because a campaign that merely ran past its deadline is overdue, not lapsed.
    due_date_lapsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    modules: Mapped[list["CampaignModule"]] = relationship(
        order_by="CampaignModule.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    targets: Mapped[list["CampaignTarget"]] = relationship(
        order_by="CampaignTarget.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    collaborators: Mapped[list["CampaignCollaborator"]] = relationship(
        order_by="CampaignCollaborator.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CampaignModule(Base):
    """One entry in a campaign's ordered module list.

    References a translation group, never a bare module, for the same reason
    `Assignment` does: a translation added later is covered automatically.
    """

    __tablename__ = "campaign_modules"
    __table_args__ = (
        CheckConstraint(
            "requirement in ('mandatory', 'recommended')", name="ck_campaign_modules_requirement"
        ),
        UniqueConstraint("campaign_id", "translation_group_id", name="uq_campaign_modules_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    # No cascade: deleting a module leaves a tombstone (Release 1), so the
    # group row outlives it and the campaign can show an unavailable marker.
    translation_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_translation_groups.id"), nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # mandatory | recommended
    requirement: Mapped[str] = mapped_column(String(20), nullable=False)


class CampaignTarget(Base):
    """Who a campaign is aimed at.

    `target_id` is deliberately not a foreign key: it names a row in `groups`
    or `users` depending on `target_type`, so existence is checked at the
    route, exactly as `Assignment` does.
    """

    __tablename__ = "campaign_targets"
    __table_args__ = (
        CheckConstraint("target_type in ('user', 'group')", name="ck_campaign_targets_type"),
        UniqueConstraint("campaign_id", "target_type", "target_id", name="uq_campaign_targets"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    # user | group
    target_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CampaignCollaborator(Base):
    """A Content Manager the creator has invited to work on a campaign.

    A collaborator has the creator's rights over metadata, modules and targets
    but not over who else is in the room: only the creator or an Administrator
    manages collaborators or deletes a draft. The row survives its creator
    being erased or losing the role, so a campaign is never orphaned out from
    under the people still working on it.
    """

    __tablename__ = "campaign_collaborators"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True, index=True
    )
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CampaignEditSession(Base):
    """Who currently has a campaign open — presence, not a lock.

    The same shape and meaning as `ModuleEditSession`: a heartbeat keeps
    `last_seen_at` fresh and an aged-out row counts as gone.
    """

    __tablename__ = "campaign_edit_sessions"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

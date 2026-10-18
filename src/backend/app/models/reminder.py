import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModuleReminder(Base):
    """One reminder email actually sent, to one learner, for one assignment.

    What both reminder paths — the scheduled cadence and the Administrator's
    manual nudge — consult before sending: a row here is what makes a second
    run of the daily job on the same day a no-op, and what the one-per-learner-
    per-module-per-day cap is checked against (joining back to `assignments`
    for the module's translation group). `kind` is the cadence checkpoint that
    produced it, or `manual` for the nudge — never itself part of the cap, which
    keys on the day and the learner alone.
    """

    __tablename__ = "module_reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # advance_7 | advance_1 | due | overdue_weekly | manual
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind in ('advance_7', 'advance_1', 'due', 'overdue_weekly', 'manual')",
            name="ck_module_reminders_kind",
        ),
    )


class CampaignReminder(Base):
    """One campaign reminder email actually sent, to one learner.

    The campaign-level counterpart of `ModuleReminder`, and the other half of
    the send log the daily cap is checked against. `translation_group_ids` is
    the mandatory material that one email listed: it is what lets a module's
    own reminder be suppressed on a day the campaign's email already covered
    it, and what lets a campaign email leave out a module the learner was
    already chased for today. Stored rather than re-derived because the
    campaign's modules can be edited between the send and the check.
    """

    __tablename__ = "campaign_reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # advance_7 | advance_1 | due | overdue_weekly | manual
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    translation_group_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind in ('advance_7', 'advance_1', 'due', 'overdue_weekly', 'manual')",
            name="ck_campaign_reminders_kind",
        ),
    )

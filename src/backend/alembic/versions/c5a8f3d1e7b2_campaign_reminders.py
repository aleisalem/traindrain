"""campaign_reminders: the send log for campaign-level reminder emails

Revision ID: c5a8f3d1e7b2
Revises: b9d4e2a6c1f8
Create Date: 2026-10-18 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5a8f3d1e7b2'
down_revision: str | Sequence[str] | None = 'b9d4e2a6c1f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaign_reminders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'campaign_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('campaigns.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column(
            'translation_group_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False
        ),
        sa.Column(
            'sent_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind in ('advance_7', 'advance_1', 'due', 'overdue_weekly', 'manual')",
            name='ck_campaign_reminders_kind',
        ),
    )
    op.create_index('ix_campaign_reminders_campaign_id', 'campaign_reminders', ['campaign_id'])
    op.create_index('ix_campaign_reminders_user_id', 'campaign_reminders', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_campaign_reminders_user_id', table_name='campaign_reminders')
    op.drop_index('ix_campaign_reminders_campaign_id', table_name='campaign_reminders')
    op.drop_table('campaign_reminders')

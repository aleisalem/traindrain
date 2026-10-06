"""campaigns: drafts with ordered modules and targets

Revision ID: e7b3c91a4d26
Revises: d8f3a4c2b6e1
Create Date: 2026-10-06 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7b3c91a4d26'
down_revision: str | Sequence[str] | None = 'd8f3a4c2b6e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaigns',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('sequential', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('auto_reminders', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status in ('draft', 'active', 'suspended', 'closed')", name='ck_campaigns_status'
        ),
        sa.CheckConstraint(
            'start_date is null or due_date is null or due_date >= start_date',
            name='ck_campaigns_dates_ordered',
        ),
    )
    op.create_index('ix_campaigns_created_by', 'campaigns', ['created_by'])

    op.create_table(
        'campaign_modules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        # A translation group, never a bare module, so a variant added later is
        # covered automatically. No cascade: a deleted module leaves a
        # tombstone, so the group row outlives it.
        sa.Column('translation_group_id', sa.UUID(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('requirement', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['translation_group_id'], ['module_translation_groups.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "requirement in ('mandatory', 'recommended')", name='ck_campaign_modules_requirement'
        ),
        sa.UniqueConstraint(
            'campaign_id', 'translation_group_id', name='uq_campaign_modules_group'
        ),
    )
    op.create_index('ix_campaign_modules_campaign_id', 'campaign_modules', ['campaign_id'])
    op.create_index(
        'ix_campaign_modules_translation_group_id', 'campaign_modules', ['translation_group_id']
    )

    op.create_table(
        'campaign_targets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('target_type', sa.String(length=10), nullable=False),
        # Not a foreign key: names a row in `groups` or `users` depending on
        # `target_type`; existence is checked at the route, as assignments do.
        sa.Column('target_id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("target_type in ('user', 'group')", name='ck_campaign_targets_type'),
        sa.UniqueConstraint(
            'campaign_id', 'target_type', 'target_id', name='uq_campaign_targets'
        ),
    )
    op.create_index('ix_campaign_targets_campaign_id', 'campaign_targets', ['campaign_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_campaign_targets_campaign_id', table_name='campaign_targets')
    op.drop_table('campaign_targets')
    op.drop_index('ix_campaign_modules_translation_group_id', table_name='campaign_modules')
    op.drop_index('ix_campaign_modules_campaign_id', table_name='campaign_modules')
    op.drop_table('campaign_modules')
    op.drop_index('ix_campaigns_created_by', table_name='campaigns')
    op.drop_table('campaigns')

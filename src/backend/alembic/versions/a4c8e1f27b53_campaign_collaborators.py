"""campaign collaborators and edit sessions

Revision ID: a4c8e1f27b53
Revises: e7b3c91a4d26
Create Date: 2026-10-06 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4c8e1f27b53'
down_revision: str | Sequence[str] | None = 'e7b3c91a4d26'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaign_collaborators',
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('added_by', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['added_by'], ['users.id']),
        sa.PrimaryKeyConstraint('campaign_id', 'user_id'),
    )
    op.create_index(
        'ix_campaign_collaborators_user_id', 'campaign_collaborators', ['user_id']
    )

    op.create_table(
        'campaign_edit_sessions',
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column(
            'last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('campaign_id', 'user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('campaign_edit_sessions')
    op.drop_index('ix_campaign_collaborators_user_id', table_name='campaign_collaborators')
    op.drop_table('campaign_collaborators')

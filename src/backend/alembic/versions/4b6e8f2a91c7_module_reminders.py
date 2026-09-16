"""module reminders: idempotency and the daily cap for both reminder paths

Revision ID: 4b6e8f2a91c7
Revises: 2c9a4e6b1f73
Create Date: 2026-09-16 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4b6e8f2a91c7'
down_revision: str | Sequence[str] | None = '2c9a4e6b1f73'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'module_reminders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('assignment_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        # advance_7 | advance_1 | due | overdue_weekly | manual
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column(
            'sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "kind in ('advance_7', 'advance_1', 'due', 'overdue_weekly', 'manual')",
            name='ck_module_reminders_kind',
        ),
    )
    op.create_index('ix_module_reminders_assignment_id', 'module_reminders', ['assignment_id'])
    # The daily-cap query is always "has this user had a reminder for this
    # group since midnight" — user_id + sent_at is the pair it filters on.
    op.create_index('ix_module_reminders_user_sent_at', 'module_reminders', ['user_id', 'sent_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_module_reminders_user_sent_at', table_name='module_reminders')
    op.drop_index('ix_module_reminders_assignment_id', table_name='module_reminders')
    op.drop_table('module_reminders')

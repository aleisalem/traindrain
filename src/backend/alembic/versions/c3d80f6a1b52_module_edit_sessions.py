"""module edit sessions

Revision ID: c3d80f6a1b52
Revises: b7e21d94c5a3
Create Date: 2026-09-09 01:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d80f6a1b52'
down_revision: str | Sequence[str] | None = 'b7e21d94c5a3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'module_edit_sessions',
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column(
            'last_seen_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('module_id', 'user_id'),
    )
    # Presence is always read as "who is on this module, seen recently".
    op.create_index(
        'ix_module_edit_sessions_module_last_seen',
        'module_edit_sessions',
        ['module_id', 'last_seen_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_module_edit_sessions_module_last_seen', table_name='module_edit_sessions'
    )
    op.drop_table('module_edit_sessions')

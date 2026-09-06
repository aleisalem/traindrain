"""groups and membership

Revision ID: 58cc588f1675
Revises: 6c0140842509
Create Date: 2026-09-06 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '58cc588f1675'
down_revision: str | Sequence[str] | None = '6c0140842509'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'groups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'group_members',
        sa.Column('group_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('group_id', 'user_id'),
    )
    op.create_table(
        'invite_groups',
        sa.Column('invite_id', sa.UUID(), nullable=False),
        sa.Column('group_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['invite_id'], ['invites.id']),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('invite_id', 'group_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('invite_groups')
    op.drop_table('group_members')
    op.drop_table('groups')

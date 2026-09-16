"""assignments: who has to read a body of material, and by when

Revision ID: 2c9a4e6b1f73
Revises: 1a2b3c4d5e6f
Create Date: 2026-09-16 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c9a4e6b1f73'
down_revision: str | Sequence[str] | None = '1a2b3c4d5e6f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        # Always a translation group, never a bare module — a variant added
        # later is automatically covered by an assignment made before it
        # existed.
        sa.Column('translation_group_id', sa.UUID(), nullable=False),
        sa.Column('target_type', sa.String(length=10), nullable=False),
        # Not a foreign key: this names a row in `groups` or in `users`
        # depending on `target_type`, and a polymorphic reference cannot be
        # declared as one constraint. Existence is checked at the route.
        sa.Column('target_id', sa.UUID(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('requirement', sa.String(length=20), nullable=False),
        sa.Column('auto_reminders', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('assigned_by', sa.UUID(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['translation_group_id'], ['module_translation_groups.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("target_type in ('user', 'group')", name='ck_assignments_target_type'),
        sa.CheckConstraint(
            "requirement in ('mandatory', 'recommended')", name='ck_assignments_requirement'
        ),
        # One assignment per (material, target) pair: a second attempt to
        # assign the same group or person again is a conflict, not a second
        # round of emails.
        sa.UniqueConstraint(
            'translation_group_id', 'target_type', 'target_id', name='uq_assignments_target'
        ),
    )
    op.create_index(
        'ix_assignments_translation_group_id', 'assignments', ['translation_group_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_assignments_translation_group_id', table_name='assignments')
    op.drop_table('assignments')

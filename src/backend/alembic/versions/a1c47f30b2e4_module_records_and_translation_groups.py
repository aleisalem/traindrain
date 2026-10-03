"""module records and translation groups

Revision ID: a1c47f30b2e4
Revises: 58cc588f1675
Create Date: 2026-09-09 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c47f30b2e4'
down_revision: str | Sequence[str] | None = '58cc588f1675'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The two tables reference each other (a module names its group; a group
    # names its primary module), so primary_module_id's foreign key is added
    # after both tables exist rather than inline here.
    op.create_table(
        'module_translation_groups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('primary_module_id', sa.UUID(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'modules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('translation_group_id', sa.UUID(), nullable=False),
        sa.Column('language', sa.String(length=5), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('estimated_duration_minutes', sa.Integer(), nullable=True),
        sa.Column(
            'catalog_visible', sa.Boolean(), server_default=sa.text('false'), nullable=False
        ),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('draft_revision', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('last_edited_by', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['translation_group_id'], ['module_translation_groups.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['last_edited_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        # One variant per language per body of material.
        sa.UniqueConstraint('translation_group_id', 'language'),
    )
    op.create_index('ix_modules_translation_group_id', 'modules', ['translation_group_id'])
    op.create_foreign_key(
        'fk_translation_group_primary_module',
        'module_translation_groups',
        'modules',
        ['primary_module_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_translation_group_primary_module', 'module_translation_groups', type_='foreignkey'
    )
    op.drop_index('ix_modules_translation_group_id', table_name='modules')
    op.drop_table('modules')
    op.drop_table('module_translation_groups')

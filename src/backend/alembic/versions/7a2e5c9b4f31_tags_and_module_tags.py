"""tags and module_tags: free-text labels a module can carry

Revision ID: 7a2e5c9b4f31
Revises: 4b6e8f2a91c7
Create Date: 2026-09-25 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7a2e5c9b4f31'
down_revision: str | Sequence[str] | None = '4b6e8f2a91c7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tags',
        sa.Column('id', sa.UUID(), nullable=False),
        # Normalized to lowercase and deduplicated at write time, so this
        # constraint is what turns a race between two authors typing the same
        # new tag into one row rather than two.
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_tags_name'),
    )
    op.create_table(
        'module_tags',
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('module_id', 'tag_id'),
    )
    op.create_index('ix_module_tags_tag_id', 'module_tags', ['tag_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_module_tags_tag_id', table_name='module_tags')
    op.drop_table('module_tags')
    op.drop_table('tags')

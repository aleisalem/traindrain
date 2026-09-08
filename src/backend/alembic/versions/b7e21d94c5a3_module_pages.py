"""module pages

Revision ID: b7e21d94c5a3
Revises: a1c47f30b2e4
Create Date: 2026-09-09 00:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.module import SEARCH_TSV_EXPRESSION

# revision identifiers, used by Alembic.
revision: str = 'b7e21d94c5a3'
down_revision: str | Sequence[str] | None = 'a1c47f30b2e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'module_pages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('search_config', sa.String(length=20), nullable=False),
        sa.Column('search_text', sa.Text(), nullable=True),
        sa.Column(
            'search_tsv',
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_TSV_EXPRESSION, persisted=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # DEFERRABLE so a reorder can renumber every page in one transaction
        # without a transient collision between two rows mid-update.
        sa.UniqueConstraint(
            'module_id', 'position', deferrable=True, initially='DEFERRED'
        ),
    )
    op.create_index('ix_module_pages_module_id', 'module_pages', ['module_id'])
    op.create_index(
        'ix_module_pages_search_tsv', 'module_pages', ['search_tsv'], postgresql_using='gin'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_module_pages_search_tsv', table_name='module_pages')
    op.drop_index('ix_module_pages_module_id', table_name='module_pages')
    op.drop_table('module_pages')

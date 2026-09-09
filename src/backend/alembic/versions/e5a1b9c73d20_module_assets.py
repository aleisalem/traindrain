"""module assets

Revision ID: e5a1b9c73d20
Revises: c3d80f6a1b52
Create Date: 2026-09-09 10:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5a1b9c73d20'
down_revision: str | Sequence[str] | None = 'c3d80f6a1b52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'module_assets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        # `modules/{module_id}/assets/{asset_id}`, built from opaque UUIDs.
        sa.Column('object_key', sa.String(length=300), nullable=False),
        # What the bytes turned out to be, never what the client declared.
        sa.Column('content_type', sa.String(length=120), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('original_filename', sa.String(length=200), nullable=False),
        sa.Column('uploaded_by', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint("kind in ('image', 'attachment')", name='ck_module_assets_kind'),
        sa.CheckConstraint('size_bytes > 0', name='ck_module_assets_size_positive'),
        # Deleting a module takes its asset rows with it; purging the stored
        # objects themselves is the delete route's job (ticket 11), because the
        # database cannot reach into the object store.
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('object_key', name='uq_module_assets_object_key'),
    )
    # Assets are always read as "everything on this module", newest first.
    op.create_index(
        'ix_module_assets_module_created',
        'module_assets',
        ['module_id', 'created_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_module_assets_module_created', table_name='module_assets')
    op.drop_table('module_assets')

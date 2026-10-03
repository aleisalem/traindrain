"""module deleted_version_number: the tombstone's memory of its last version

Revision ID: d8f3a4c2b6e1
Revises: 7a2e5c9b4f31
Create Date: 2026-09-25 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8f3a4c2b6e1'
down_revision: str | Sequence[str] | None = '7a2e5c9b4f31'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ticket 11's delete clears `current_version_id` (its version rows are
    # gone) but a tombstone still has to say what version it was on — this is
    # that memory, written once, at delete time, and never touched again.
    op.add_column('modules', sa.Column('deleted_version_number', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('modules', 'deleted_version_number')

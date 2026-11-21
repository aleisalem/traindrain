"""campaigns: due_date_lapsed flag for resume-after-the-deadline

Revision ID: b9d4e2a6c1f8
Revises: a4c8e1f27b53
Create Date: 2026-10-07 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9d4e2a6c1f8'
down_revision: str | Sequence[str] | None = 'a4c8e1f27b53'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'campaigns',
        sa.Column('due_date_lapsed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('campaigns', 'due_date_lapsed')

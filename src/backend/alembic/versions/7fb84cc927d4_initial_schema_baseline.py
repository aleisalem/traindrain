"""initial schema baseline

Revision ID: 7fb84cc927d4
Revises: 
Create Date: 2026-09-01 23:05:11.988910

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '7fb84cc927d4'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""

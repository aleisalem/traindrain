"""pair completed_version_number with the module it was completed against

Revision ID: f5e3fde400c4
Revises: a7c1d9e35f80
Create Date: 2026-09-12 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5e3fde400c4'
down_revision: str | Sequence[str] | None = 'a7c1d9e35f80'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `module_progress.module_id` moves on an explicit language switch (ticket
    # 6) — it names whichever variant the learner is *currently* reading, not
    # necessarily the one they completed. Without a column of its own,
    # `completed_version_number` would be left describing a version number
    # under a module id that has since moved on to a different variant's own
    # numbering, which is exactly the kind of mismatch a report must not show.
    op.add_column(
        'module_progress', sa.Column('completed_module_id', sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        'fk_module_progress_completed_module',
        'module_progress',
        'modules',
        ['completed_module_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_module_progress_completed_module', 'module_progress', type_='foreignkey'
    )
    op.drop_column('module_progress', 'completed_module_id')

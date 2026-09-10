"""learner progress through a module

Revision ID: a7c1d9e35f80
Revises: f2b31c8a7d94
Create Date: 2026-09-10 11:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c1d9e35f80'
down_revision: str | Sequence[str] | None = 'f2b31c8a7d94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `catalog_visible` is not added here: it has been on `modules` since the
    # table was created (a1c47f30b2e4), defaulting to false. Implicit deny —
    # material reaches nobody until an author says so — is a property of the
    # column's default, so it was never something to bolt on later.
    op.create_table(
        'module_progress',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('translation_group_id', sa.UUID(), nullable=False),
        # The variant actually read, so a report can say which text somebody
        # was shown. Not cascaded: deleting a module leaves a tombstone row
        # (ticket 11), and the completion record has to keep resolving.
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column(
            'pages_viewed',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        # No foreign key, deliberately: page ids come from an immutable version
        # snapshot, and the draft page one of them names may have been deleted
        # by an author since. A constraint would either break a learner's
        # bookmark or block an edit the author is entitled to make.
        sa.Column('current_page_id', sa.UUID(), nullable=True),
        sa.Column(
            'started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_version_number', sa.Integer(), nullable=True),
        # Written by a substantive republish (ticket 7). Never clears
        # `completed_at`: the learner did read that version, on that date.
        sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['translation_group_id'], ['module_translation_groups.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id']),
        sa.PrimaryKeyConstraint('id'),
        # One record per learner per body of material, whichever language
        # variant they read — which is what makes a language switch a
        # continuation rather than a second, competing journey.
        sa.UniqueConstraint(
            'user_id', 'translation_group_id', name='uq_module_progress_learner'
        ),
    )
    # No further index: every query this release makes leads with `user_id`,
    # which the unique constraint above already serves. Reporting reads a whole
    # translation group at once and can add its own index when it exists.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('module_progress')

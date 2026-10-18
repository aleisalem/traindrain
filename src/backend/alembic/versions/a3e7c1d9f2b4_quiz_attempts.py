"""quiz attempts and the score/quiz version recorded on a completion

Revision ID: a3e7c1d9f2b4
Revises: f1d6a8c3b9e4
Create Date: 2026-10-18 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3e7c1d9f2b4'
down_revision: str | Sequence[str] | None = 'f1d6a8c3b9e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'quiz_attempts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'translation_group_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('module_translation_groups.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'module_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('modules.id'), nullable=False
        ),
        # The frozen version whose quiz was taken. Cascades with the version,
        # i.e. only when the whole module is deleted.
        sa.Column(
            'version_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('module_versions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('shuffle_seed', sa.BigInteger(), nullable=False),
        sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('score_percent', sa.Integer(), nullable=True),
        sa.Column('correct_count', sa.Integer(), nullable=True),
        sa.Column('total_questions', sa.Integer(), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=True),
        sa.Column('question_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            'started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
    )
    op.create_index(
        'ix_quiz_attempts_learner', 'quiz_attempts', ['user_id', 'translation_group_id']
    )
    # At most one attempt in progress per learner and material.
    op.create_index(
        'uq_quiz_attempts_one_open',
        'quiz_attempts',
        ['user_id', 'translation_group_id'],
        unique=True,
        postgresql_where=sa.text('submitted_at is null'),
    )
    op.add_column('module_progress', sa.Column('completed_score_percent', sa.Integer(), nullable=True))
    op.add_column(
        'module_progress', sa.Column('completed_quiz_version_number', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('module_progress', 'completed_quiz_version_number')
    op.drop_column('module_progress', 'completed_score_percent')
    op.drop_index('uq_quiz_attempts_one_open', table_name='quiz_attempts')
    op.drop_index('ix_quiz_attempts_learner', table_name='quiz_attempts')
    op.drop_table('quiz_attempts')

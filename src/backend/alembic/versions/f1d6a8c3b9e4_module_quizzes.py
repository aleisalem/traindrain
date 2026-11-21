"""module quizzes: draft quiz, questions and options

Revision ID: f1d6a8c3b9e4
Revises: c5a8f3d1e7b2
Create Date: 2026-10-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1d6a8c3b9e4'
down_revision: str | Sequence[str] | None = 'c5a8f3d1e7b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Only the *draft* is stored relationally. The published quiz is frozen into
    `module_versions.snapshot["quiz"]` — a JSONB column the existing
    `trg_module_versions_immutable` trigger already protects — so no new
    immutability machinery is needed.
    """
    op.create_table(
        'module_quizzes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'module_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('modules.id', ondelete='CASCADE'),
            nullable=False,
            unique=True,
        ),
        sa.Column('pass_mark_percent', sa.Integer(), nullable=False, server_default='80'),
        sa.Column('max_attempts', sa.Integer(), nullable=True),
        sa.Column('shuffle', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('reveal_after_pass', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.CheckConstraint(
            'pass_mark_percent between 1 and 100', name='ck_module_quizzes_pass_mark'
        ),
        sa.CheckConstraint(
            'max_attempts is null or max_attempts >= 1', name='ck_module_quizzes_max_attempts'
        ),
    )
    op.create_table(
        'quiz_questions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'quiz_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('module_quizzes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('prompt', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('explanation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.UniqueConstraint(
            'quiz_id', 'position', deferrable=True, initially='DEFERRED',
            name='uq_quiz_questions_quiz_id_position',
        ),
    )
    op.create_index('ix_quiz_questions_quiz_id', 'quiz_questions', ['quiz_id'])
    op.create_table(
        'quiz_options',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'question_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('quiz_questions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(500), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint(
            'question_id', 'position', deferrable=True, initially='DEFERRED',
            name='uq_quiz_options_question_id_position',
        ),
    )
    op.create_index('ix_quiz_options_question_id', 'quiz_options', ['question_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_quiz_options_question_id', table_name='quiz_options')
    op.drop_table('quiz_options')
    op.drop_index('ix_quiz_questions_quiz_id', table_name='quiz_questions')
    op.drop_table('quiz_questions')
    op.drop_table('module_quizzes')

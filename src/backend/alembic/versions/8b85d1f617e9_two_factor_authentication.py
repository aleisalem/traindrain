"""two-factor authentication

Revision ID: 8b85d1f617e9
Revises: d054ae5c8251
Create Date: 2026-09-03 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8b85d1f617e9'
down_revision: str | Sequence[str] | None = 'd054ae5c8251'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('two_factor_credentials',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('encrypted_secret', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('recovery_codes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('code_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recovery_codes_user_id'), 'recovery_codes', ['user_id'], unique=False)
    op.create_table('two_factor_challenges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_two_factor_challenges_user_id'), 'two_factor_challenges', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_two_factor_challenges_user_id'), table_name='two_factor_challenges')
    op.drop_table('two_factor_challenges')
    op.drop_index(op.f('ix_recovery_codes_user_id'), table_name='recovery_codes')
    op.drop_table('recovery_codes')
    op.drop_table('two_factor_credentials')

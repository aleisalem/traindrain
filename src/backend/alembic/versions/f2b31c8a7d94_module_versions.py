"""module version snapshots

Revision ID: f2b31c8a7d94
Revises: e5a1b9c73d20
Create Date: 2026-09-10 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2b31c8a7d94'
down_revision: str | Sequence[str] | None = 'e5a1b9c73d20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'module_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column(
            'published_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('published_by', sa.UUID(), nullable=False),
        sa.Column('revision_kind', sa.String(length=20), nullable=False),
        # The whole of what a learner reads at this version: title,
        # description, language, and the full page array, frozen at publish
        # time. A completion record can then name exactly what was read, which
        # a pointer into the live draft could never do.
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "revision_kind in ('minor', 'substantive')", name='ck_module_versions_revision_kind'
        ),
        sa.CheckConstraint('version_number > 0', name='ck_module_versions_number_positive'),
        # Ticket 11's delete purges a module's snapshots along with its pages;
        # nothing short of that deletion ever removes one.
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['published_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('module_id', 'version_number', name='uq_module_versions_number'),
    )
    # Version history is always read as "every version of this module, newest
    # first", and the next version number is the max over the same rows.
    op.create_index(
        'ix_module_versions_module_number', 'module_versions', ['module_id', 'version_number']
    )

    # What learners read. Nullable: a module that has never been published has
    # no version, and unpublishing deliberately leaves this pointing at the
    # last one so history survives and republishing is a status change.
    op.add_column('modules', sa.Column('current_version_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_modules_current_version',
        'modules',
        'module_versions',
        ['current_version_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # Immutability, enforced where it cannot be forgotten. A version snapshot
    # is the evidence of what somebody was made to read; a later UPDATE would
    # rewrite that record silently, so the database refuses one outright rather
    # than trusting every future route to leave the row alone.
    op.execute(
        """
        CREATE FUNCTION module_versions_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'module_versions rows are immutable once written (module %, version %)',
                OLD.module_id, OLD.version_number;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_module_versions_immutable
        BEFORE UPDATE ON module_versions
        FOR EACH ROW EXECUTE FUNCTION module_versions_reject_update()
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP TRIGGER IF EXISTS trg_module_versions_immutable ON module_versions')
    op.execute('DROP FUNCTION IF EXISTS module_versions_reject_update()')
    op.drop_constraint('fk_modules_current_version', 'modules', type_='foreignkey')
    op.drop_column('modules', 'current_version_id')
    op.drop_index('ix_module_versions_module_number', table_name='module_versions')
    op.drop_table('module_versions')

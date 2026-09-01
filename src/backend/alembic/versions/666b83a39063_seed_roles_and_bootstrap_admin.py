"""seed roles and bootstrap admin

Revision ID: 666b83a39063
Revises: 23f36c7eccd1
Create Date: 2026-09-01 23:32:54.449376

"""
import logging
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.config import get_settings
from app.security.passwords import generate_random_password, hash_password

# revision identifiers, used by Alembic.
revision: str = '666b83a39063'
down_revision: str | Sequence[str] | None = '23f36c7eccd1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("traindrain.bootstrap")

ROLE_SEED = (
    ("Administrator", "Full read-write access to all Release 0 functionality."),
    ("Content Manager", "Functionally identical to Learner until content features ship."),
    ("Learner", "Read-write access to their own account only."),
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    roles = sa.table(
        "roles",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.UUID()),
        sa.column("email", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("must_change_password", sa.Boolean()),
    )
    user_roles = sa.table(
        "user_roles",
        sa.column("user_id", sa.UUID()),
        sa.column("role_id", sa.UUID()),
    )

    role_ids: dict[str, uuid.UUID] = {}
    for name, description in ROLE_SEED:
        role_id = uuid.uuid4()
        role_ids[name] = role_id
        bind.execute(roles.insert().values(id=role_id, name=name, description=description))

    admin_email = get_settings().bootstrap_admin_email
    admin_password = generate_random_password()
    admin_id = uuid.uuid4()
    bind.execute(
        users.insert().values(
            id=admin_id,
            email=admin_email,
            password_hash=hash_password(admin_password),
            must_change_password=True,
        )
    )
    bind.execute(user_roles.insert().values(user_id=admin_id, role_id=role_ids["Administrator"]))

    # Logged once, here, and nowhere else — SES infra doesn't exist yet at this point.
    logger.warning(
        "Bootstrap Administrator account created. email=%s password=%s "
        "(must be changed on first login)",
        admin_email,
        admin_password,
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    admin_email = get_settings().bootstrap_admin_email
    bind.execute(
        sa.text(
            "DELETE FROM user_roles WHERE user_id = (SELECT id FROM users WHERE email = :email)"
        ),
        {"email": admin_email},
    )
    bind.execute(sa.text("DELETE FROM users WHERE email = :email"), {"email": admin_email})
    bind.execute(
        sa.text("DELETE FROM roles WHERE name IN ('Administrator', 'Content Manager', 'Learner')")
    )

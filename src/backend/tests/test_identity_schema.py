import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Role, User
from app.security.passwords import hash_password

EXPECTED_ROLE_NAMES = {"Administrator", "Content Manager", "Learner"}


async def test_three_roles_are_seeded(db_session: AsyncSession) -> None:
    roles = (await db_session.execute(select(Role))).scalars().all()
    assert {role.name for role in roles} == EXPECTED_ROLE_NAMES


async def test_bootstrap_admin_exists_with_hashed_password_and_forced_change(
    db_session: AsyncSession,
) -> None:
    admin_email = get_settings().bootstrap_admin_email
    admin = (
        await db_session.execute(select(User).where(User.email == admin_email))
    ).scalar_one()

    assert admin.must_change_password is True
    assert admin.password_hash != ""
    # An Argon2id hash never equals the plaintext and always carries this prefix.
    assert admin.password_hash.startswith("$argon2id$")


async def test_bootstrap_admin_holds_administrator_role(db_session: AsyncSession) -> None:
    admin_email = get_settings().bootstrap_admin_email
    admin = (
        await db_session.execute(select(User).where(User.email == admin_email))
    ).scalar_one()

    assert {role.name for role in admin.roles} == {"Administrator"}


async def test_email_uniqueness_is_case_insensitive(db_session: AsyncSession) -> None:
    password_hash = hash_password("irrelevant-password-value")
    db_session.add(
        User(id=uuid.uuid4(), email="Case.Test@Example.com", password_hash=password_hash)
    )
    await db_session.flush()

    db_session.add(
        User(id=uuid.uuid4(), email="case.test@example.com", password_hash=password_hash)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

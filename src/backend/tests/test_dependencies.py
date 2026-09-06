import uuid

import pytest
from fastapi import HTTPException

from app.dependencies import require_active_user, require_administrator
from app.models import Role, User
from app.security.passwords import hash_password


def _make_user(*, must_change_password: bool) -> User:
    return User(
        id=uuid.uuid4(),
        email="gate-test@example.com",
        password_hash=hash_password("irrelevant-password-value"),
        must_change_password=must_change_password,
    )


def _make_user_with_roles(*, role_names: list[str]) -> User:
    user = _make_user(must_change_password=False)
    user.roles = [Role(id=uuid.uuid4(), name=name) for name in role_names]
    return user


async def test_require_active_user_blocks_forced_password_change() -> None:
    user = _make_user(must_change_password=True)

    with pytest.raises(HTTPException) as exc_info:
        await require_active_user(user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "password_change_required"


async def test_require_active_user_allows_a_user_who_has_set_their_password() -> None:
    user = _make_user(must_change_password=False)

    result = await require_active_user(user=user)

    assert result is user


async def test_require_administrator_allows_an_administrator() -> None:
    user = _make_user_with_roles(role_names=["Administrator"])

    result = await require_administrator(user=user)

    assert result is user


async def test_require_administrator_blocks_a_learner() -> None:
    user = _make_user_with_roles(role_names=["Learner"])

    with pytest.raises(HTTPException) as exc_info:
        await require_administrator(user=user)

    assert exc_info.value.status_code == 403


async def test_require_administrator_blocks_a_user_with_no_roles() -> None:
    user = _make_user_with_roles(role_names=[])

    with pytest.raises(HTTPException) as exc_info:
        await require_administrator(user=user)

    assert exc_info.value.status_code == 403

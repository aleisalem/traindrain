from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AuditLog, User
from app.security.audit import record_audit_log


async def _bootstrap_admin(db_session: AsyncSession) -> User:
    result = await db_session.execute(
        select(User).where(User.email == get_settings().bootstrap_admin_email)
    )
    return result.scalar_one()


async def test_record_audit_log_writes_expected_fields(db_session: AsyncSession) -> None:
    admin = await _bootstrap_admin(db_session)

    entry = await record_audit_log(
        db_session,
        actor_user_id=admin.id,
        action="test.action",
        target_user_id=admin.id,
        detail={"foo": "bar"},
    )

    assert entry.id is not None
    assert entry.timestamp is not None

    stored = await db_session.get(AuditLog, entry.id)
    assert stored is not None
    assert stored.actor_user_id == admin.id
    assert stored.action == "test.action"
    assert stored.target_user_id == admin.id
    assert stored.detail == {"foo": "bar"}


async def test_record_audit_log_defaults_target_and_detail(db_session: AsyncSession) -> None:
    admin = await _bootstrap_admin(db_session)

    entry = await record_audit_log(db_session, actor_user_id=admin.id, action="system.action")

    stored = await db_session.get(AuditLog, entry.id)
    assert stored is not None
    assert stored.target_user_id is None
    assert stored.detail == {}

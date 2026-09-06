import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record_audit_log(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    # Flushes but doesn't commit, so this can join a caller's larger transaction.
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        target_user_id=target_user_id,
        detail=detail or {},
    )
    session.add(entry)
    await session.flush()
    return entry

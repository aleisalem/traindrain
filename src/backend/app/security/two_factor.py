import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecoveryCode, TwoFactorCredential


async def delete_two_factor_credential(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Remove a user's TOTP credential and any remaining recovery codes.

    Shared by self-service and admin-initiated disable — doesn't commit, so
    it can join the caller's own session-revocation and audit-log writes.
    """
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    await db.execute(delete(TwoFactorCredential).where(TwoFactorCredential.user_id == user_id))

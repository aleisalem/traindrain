import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TwoFactorCredential(Base):
    # One row per user (user_id is the primary key, not a surrogate id).
    # `enabled_at` is null while enrollment is pending confirmation (a secret
    # has been generated but not yet proven via a real TOTP code) and set
    # once the user confirms it via /enable.
    __tablename__ = "two_factor_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    # Envelope-encrypted (AES-256-GCM, app-layer key) — never stored in
    # plaintext, layered on top of RDS encryption-at-rest.
    encrypted_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryCode(Base):
    # Argon2id-hashed, same treatment as passwords. Consumed (used_at set) on
    # first use — never reusable.
    __tablename__ = "recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TwoFactorChallenge(Base):
    # Bridges "password verified" and "session issued" while the second
    # factor is pending. Referenced by a short-lived httpOnly cookie, never
    # exposed to page JS — the same treatment the real session cookie gets.
    __tablename__ = "two_factor_challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

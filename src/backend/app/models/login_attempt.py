import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LoginAttempt(Base):
    # One row per failed login. The sliding window is computed by counting rows
    # within the lookback window at check time — no separate counter to reset.
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_ip_created_at", "email", "ip_address", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

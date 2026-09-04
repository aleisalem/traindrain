import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.role import Role, user_roles


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness — email is the username/invite-targeting key.
        Index("ix_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preferred_language: Mapped[str | None] = mapped_column(String(5))
    preferred_theme: Mapped[str | None] = mapped_column(String(20))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

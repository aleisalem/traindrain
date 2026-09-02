import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.role import Role

invite_roles = Table(
    "invite_roles",
    Base.metadata,
    Column("invite_id", UUID(as_uuid=True), ForeignKey("invites.id"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
)


class Invite(Base):
    # token_hash, not the raw token, so a DB leak alone can't be used to accept it.
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Single-use: set once the invite is accepted, and never cleared.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a re-invite to the same email supersedes this one.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[Role]] = relationship(secondary=invite_roles, lazy="selectin")

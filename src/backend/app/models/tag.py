import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

module_tags = Table(
    "module_tags",
    Base.metadata,
    Column(
        "module_id", UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    """A free-text label a Content Manager attaches to a module.

    Normalized to lowercase and deduplicated at write time
    (`app.search.get_or_create_tags`), so "Phishing" and "phishing" are the
    same tag rather than two rows that happen to look alike.
    """

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

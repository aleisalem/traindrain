from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SystemSetting(Base):
    # A small key/value table for the handful of admin-configurable global
    # settings Release 0 needs (currently just the invite expiry) — not a
    # generic settings framework, just enough to avoid a schema migration
    # every time a new one shows up.
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)

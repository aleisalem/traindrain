import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://traindrain:traindrain@localhost:5433/traindrain",
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest_asyncio.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    # Schema + seed data (roles, bootstrap admin) must exist before any test queries them.
    command.upgrade(_alembic_config(), "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    # Rolled back after each test so tests can write freely without polluting the shared database.
    from app.db import engine

    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()

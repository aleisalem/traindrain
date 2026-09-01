import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
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


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    # Routes run against the same in-transaction session as the test, so
    # writes a test makes through HTTP are visible to it and get rolled back
    # afterward like everything else db_session touches.
    from app.db import get_db
    from app.dependencies import get_http_client
    from app.main import app

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def override_get_http_client() -> AsyncIterator[httpx.AsyncClient]:
        # Reports every password as "not pwned" by default; override again
        # per-test to exercise the breach-rejection path.
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text=""))
        async with httpx.AsyncClient(transport=transport) as mock_client:
            yield mock_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_http_client] = override_get_http_client
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://traindrain:traindrain@localhost:5432/traindrain_test",
)

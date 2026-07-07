import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _database():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = url
        os.environ["JWT_SECRET"] = "test-secret"
        os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret"
        os.environ["EMAIL_BACKEND"] = "console"
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            check=True,
            env=os.environ.copy(),
        )
        yield


@pytest_asyncio.fixture
async def client():
    from app.main import create_app

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://t"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session():
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session

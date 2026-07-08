import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from testcontainers.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _chat_body(thread_id: str, text: str = "茅台现在多少钱", state=None) -> dict:
    return {
        "commands": [
            {"type": "add-message", "message": {"role": "user", "parts": [{"type": "text", "text": text}]}}
        ],
        "threadId": thread_id,
        "state": state,
    }


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


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


@pytest.fixture
async def registered_user(client, db_session, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config

    config.get_settings.cache_clear()
    from app.auth.models import User
    from tests.test_auth_api import _register

    # 每个测试独立邮箱：DB 跨用例不回滚，同邮箱二次 request-code 会撞 60s 限流(429)
    email = f"credits-user-{uuid.uuid4().hex[:8]}@test.dev"
    token = await _register(client, db_session, email)
    row = await db_session.scalar(select(User).where(User.email == email))
    yield SimpleNamespace(id=row.id, token=token, email=email)
    config.get_settings.cache_clear()


@pytest.fixture
async def a_thread(client, registered_user):
    resp = await client.post("/api/threads/", json={}, headers=_auth(registered_user))
    return resp.json()["id"]

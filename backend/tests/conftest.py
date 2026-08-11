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
        # HS256 requires at least 256 bits. Keep tests on explicit test-only
        # keys so PyJWT warnings cannot hide actionable suite warnings.
        os.environ["JWT_SECRET"] = "test-only-jwt-secret-32-bytes-minimum"
        os.environ["JWT_REFRESH_SECRET"] = "test-only-refresh-secret-32-bytes-minimum"
        os.environ["EMAIL_BACKEND"] = "console"
        os.environ["SOCIAL_POLL_GAP_SECONDS"] = "0"  # 测试不真等风控节流间隔
        # 独立 Redis db：否则和本机 dev 后端共用 db0，它写的风控冷却（TTL 长达 24h）
        # 会把整个测试会话堵死。session_store / ratelimit 同样需要这层隔离。
        os.environ["REDIS_URL"] = "redis://localhost:6381/15"
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


@pytest_asyncio.fixture(autouse=True)
async def _clear_wechat_cooldown():
    """清掉残留的微信风控冷却。

    冷却 TTL 长达 24h，任一用例真写进去就会毒死整个会话的后续抓取用例。
    """
    from app.social.wechat import cooldown
    from app.social.weibo import cooldown as weibo_cooldown

    await cooldown.clear()
    await weibo_cooldown.clear()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clear_fund_arb_state(request):
    """Fund-arb tests use canonical codes, so isolate DB and process state."""
    from app.fund_arb.snapshot import get_store

    if "fund_arb" not in request.node.nodeid:
        yield
        return

    from sqlalchemy import delete

    from app.core.db import get_sessionmaker
    from app.fund_arb.models import (
        FundArbDaily,
        FundArbFactor,
        FundArbFund,
        FundArbReconciliation,
        FundArbTrackingDaily,
    )

    async with get_sessionmaker()() as db:
        for model in (
            FundArbReconciliation,
            FundArbFactor,
            FundArbDaily,
            FundArbTrackingDaily,
            FundArbFund,
        ):
            await db.execute(delete(model))
        await db.commit()
    get_store().clear()
    yield
    get_store().clear()


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

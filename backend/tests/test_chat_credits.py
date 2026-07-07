import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.credits import service
from tests.test_auth_api import _register


def _chat_body(thread_id: str, text: str = "茅台现在多少钱") -> dict:
    return {
        "commands": [
            {"type": "add-message", "message": {"role": "user", "parts": [{"type": "text", "text": text}]}}
        ],
        "threadId": thread_id,
        "state": None,
    }


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.fixture
async def registered_user(client, db_session, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config

    config.get_settings.cache_clear()
    from app.auth.models import User

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


@pytest.mark.asyncio
async def test_chat_rejected_when_no_credits(client, db_session, registered_user, a_thread):
    # 把余额扣到 0
    await service.charge(db_session, registered_user.id, 1000, kind="adjust")
    await db_session.commit()
    resp = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_chat_charges_after_run(client, db_session, registered_user, a_thread):
    before = await service.get_balance(db_session, registered_user.id)
    resp = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert resp.status_code == 200
    await resp.aread()  # 消费完整流
    db_session.expire_all()  # 丢弃缓存，重读账户余额
    after = await service.get_balance(db_session, registered_user.id)
    assert after < before  # 至少扣了 MIN_CHARGE

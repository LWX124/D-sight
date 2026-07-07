"""GET /api/threads/{tid}/messages：刷新后恢复聊天历史。

## checkpointer 生命周期选择（测试夹具注入共享 InMemorySaver）

ASGITransport 测试不跑 lifespan → app.state.checkpointer 缺省 → build_agent(None)
用 deepagents 的内存 checkpointer，且**跨请求不共享**（每次 build_agent 各自新建）。
若照默认，先 POST /api/chat 再 GET messages 会读到空历史，无法真实验证提取逻辑。

故本文件用自建 client 夹具，往 app.state 注入一个**共享 InMemorySaver**——这正镜像
生产里 lifespan 注入进程级 AsyncPostgresSaver 的方式：POST 与 GET 两次 build_agent
共享同一 checkpointer，历史在进程内持久，GET 端点的真实提取行为得到端到端验证（非 mock）。
"""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver

from tests.test_auth_api import _register
from tests.test_chat_api import _chat_body


@pytest_asyncio.fixture
async def ck_client(monkeypatch):
    """带共享 InMemorySaver 的 client：POST /api/chat 与 GET messages 共享 checkpointer。"""
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config

    config.get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    app.state.checkpointer = InMemorySaver()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _new_thread(client, headers) -> str:
    return (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]


async def _drain_chat(client, headers, tid, text):
    async with client.stream("POST", "/api/chat", json=_chat_body(tid, text), headers=headers) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass


async def test_messages_restored_after_chat(ck_client, db_session):
    token = await _register(ck_client, db_session, f"hist-{uuid.uuid4().hex[:8]}@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    tid = await _new_thread(ck_client, headers)

    await _drain_chat(ck_client, headers, tid, "茅台现在多少钱")

    resp = await ck_client.get(f"/api/threads/{tid}/messages", headers=headers)
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    # 恢复只需 human/ai 文本轮：human 原文 + ai 最终假回复；纯 tool_call 的空 ai 与 tool 消息被过滤
    assert [m["type"] for m in msgs] == ["human", "ai"]
    assert msgs[0]["content"] == "茅台现在多少钱"
    assert "假回复" in msgs[1]["content"]


async def test_empty_thread_returns_empty_list(ck_client, db_session):
    token = await _register(ck_client, db_session, f"hist-empty-{uuid.uuid4().hex[:8]}@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    tid = await _new_thread(ck_client, headers)

    resp = await ck_client.get(f"/api/threads/{tid}/messages", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"messages": []}


async def test_messages_foreign_thread_404(ck_client, db_session):
    token = await _register(ck_client, db_session, f"hist-a-{uuid.uuid4().hex[:8]}@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    other = await _register(ck_client, db_session, f"hist-b-{uuid.uuid4().hex[:8]}@test.dev")
    other_tid = await _new_thread(ck_client, {"Authorization": f"Bearer {other}"})

    resp = await ck_client.get(f"/api/threads/{other_tid}/messages", headers=headers)
    assert resp.status_code == 404


async def test_messages_requires_auth(ck_client):
    resp = await ck_client.get(f"/api/threads/{uuid.uuid4()}/messages")
    assert resp.status_code == 401

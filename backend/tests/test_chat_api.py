import json
import uuid

import pytest

from tests.test_auth_api import _register


def _chat_body(thread_id: str, text: str) -> dict:
    return {
        "commands": [
            {"type": "add-message", "message": {"role": "user", "parts": [{"type": "text", "text": text}]}}
        ],
        "threadId": thread_id,
        "state": None,
    }


@pytest.fixture
async def auth_and_thread(client, db_session, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config
    config.get_settings.cache_clear()
    # 每个测试独立邮箱：DB 跨用例不回滚，同邮箱二次 request-code 会撞 60s 限流(429)
    token = await _register(client, db_session, f"chat-user-{uuid.uuid4().hex[:8]}@test.dev")
    headers = {"Authorization": f"Bearer {token}"}
    tid = (await client.post("/api/threads/", json={}, headers=headers)).json()["id"]
    return headers, tid


async def test_chat_streams_fake_reply(auth_and_thread, client):
    headers, tid = auth_and_thread
    async with client.stream(
        "POST", "/api/chat", json=_chat_body(tid, "茅台现在多少钱"), headers=headers
    ) as resp:
        assert resp.status_code == 200
        # assistant-transport data-stream 走 text/plain（AI-SDK data stream 协议），非 SSE
        assert resp.headers["content-type"].startswith("text/plain")
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    # data-stream 对非 ASCII 做 JSON 转义（假回复 → 假...），故按转义形匹配
    assert json.dumps("假回复")[1:-1] in body  # fake 模型的最终文本进入了流


async def test_chat_requires_auth(client):
    resp = await client.post("/api/chat", json=_chat_body("00000000-0000-0000-0000-000000000000", "hi"))
    assert resp.status_code == 401


async def test_chat_rejects_foreign_thread(auth_and_thread, client, db_session):
    headers, _ = auth_and_thread
    other = await _register(client, db_session, f"chat-other-{uuid.uuid4().hex[:8]}@test.dev")
    other_tid = (
        await client.post("/api/threads/", json={}, headers={"Authorization": f"Bearer {other}"})
    ).json()["id"]
    resp = await client.post("/api/chat", json=_chat_body(other_tid, "hi"), headers=headers)
    assert resp.status_code == 404


async def test_chat_sets_title_and_touches_thread(auth_and_thread, client):
    headers, tid = auth_and_thread
    async with client.stream(
        "POST", "/api/chat", json=_chat_body(tid, "分析贵州茅台的投资价值，重点看护城河"), headers=headers
    ) as resp:
        async for _ in resp.aiter_text():
            pass
    threads = (await client.get("/api/threads/", headers=headers)).json()
    me = next(t for t in threads if t["id"] == tid)
    assert me["title"].startswith("分析贵州茅台")
    assert len(me["title"]) <= 30

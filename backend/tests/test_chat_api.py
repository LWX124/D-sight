import asyncio
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
    yield headers, tid
    # 清缓存，避免 fake_llm=True 泄漏到后续（如非 fake 的鉴权）用例。
    config.get_settings.cache_clear()


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

    def _updated_at(threads: list[dict]) -> str:
        return next(t for t in threads if t["id"] == tid)["updated_at"]

    before = _updated_at((await client.get("/api/threads/", headers=headers)).json())
    # 时钟分辨率保护：确保 chat 触碰能产生严格更大的 updated_at。
    await asyncio.sleep(0.01)

    async with client.stream(
        "POST", "/api/chat", json=_chat_body(tid, "分析贵州茅台的投资价值，重点看护城河"), headers=headers
    ) as resp:
        async for _ in resp.aiter_text():
            pass

    threads = (await client.get("/api/threads/", headers=headers)).json()
    me = next(t for t in threads if t["id"] == tid)
    assert me["title"].startswith("分析贵州茅台")
    assert len(me["title"]) <= 30
    # 会话被"触碰"：updated_at 严格增大（发消息刷新排序时间）。
    assert me["updated_at"] > before


async def test_timeout_surfaces_error_to_client(auth_and_thread, client, monkeypatch):
    """回归：单轮超时不得静默——必须给前端一个可见提示，而不是空流。

    复现用户"深度分析贵州茅台没有结果返回"：ai-berkshire 等重型任务跑过 15 分钟绝对
    超时后，run_callback 原本 catch TimeoutError 却不注入任何事件，前端收到既无最终
    回复、也无错误的空流 → 看着就是"没反应"。
    """
    import app.agent.build as build_mod
    import app.chat.router as chat_router
    from langchain_core.language_models import BaseChatModel
    from langchain_core.outputs import ChatResult

    class _HangingModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "hanging"

        def bind_tools(self, tools, **kw):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
            raise NotImplementedError

        async def _astream(self, messages, stop=None, run_manager=None, **kw):
            await asyncio.sleep(30)  # 远超下方注入的 0.2s 超时
            yield  # pragma: no cover

    monkeypatch.setattr(build_mod, "_make_model", lambda: _HangingModel())
    monkeypatch.setattr(chat_router, "RUN_TIMEOUT_S", 0.2)

    headers, tid = auth_and_thread
    body = ""
    async with client.stream(
        "POST", "/api/chat", json=_chat_body(tid, "深度分析贵州茅台"), headers=headers
    ) as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_text():
            body += chunk

    # 流对非 ASCII 做 \u 转义，解析 aui-state 的 JSON 载荷后按解码文本校验。
    ai_texts = []
    for line in body.splitlines():
        if not line.startswith("aui-state:"):
            continue
        for op in json.loads(line[len("aui-state:"):]):
            val = op.get("value")
            if isinstance(val, dict) and val.get("type") == "ai" and val.get("content"):
                ai_texts.append(val["content"])
    # 修复前：无任何 AI 消息（只有回显的用户消息）→ 空流 → 断言失败即复现 bug。
    assert ai_texts, f"超时后未向前端注入任何 AI 提示，流里只有回显消息：{body!r}"
    assert any("中断" in t or "上限" in t for t in ai_texts), f"AI 提示未说明超时：{ai_texts!r}"

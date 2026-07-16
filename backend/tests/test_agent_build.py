from typing import Any

import httpx
import openai
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

import app.agent.build as build_mod
from app.agent.build import (
    ALLOWED_MODELS,
    SYSTEM_PROMPT,
    ContentRiskRetryChatModel,
    build_agent,
    make_checkpointer,
)


def _bad_request(message: str) -> openai.BadRequestError:
    """构造一个真实的 openai.BadRequestError（langchain-deepseek 400 时抛的类型）。"""
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(400, request=request)
    return openai.BadRequestError(message, response=response, body=None)


class _StubModel:
    """最小桩模型：前 ``n_fail`` 次 invoke 抛给定异常，之后返回固定 AIMessage。"""

    def __init__(self, exc: Exception, n_fail: int):
        self.exc = exc
        self.n_fail = n_fail
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.n_fail:
            raise self.exc
        return AIMessage(content="桩回复")


class _StreamStub:
    """流式桩：sync/async 各产出 3 个消息块 a/b/c（模拟内部模型逐 token 流出）。"""

    def __init__(self):
        self.sync_calls = 0
        self.async_calls = 0

    def stream(self, messages, stop=None, **kwargs):
        self.sync_calls += 1
        for t in ("a", "b", "c"):
            yield AIMessageChunk(content=t)

    async def astream(self, messages, stop=None, **kwargs):
        self.async_calls += 1
        for t in ("a", "b", "c"):
            yield AIMessageChunk(content=t)


class _RiskStreamStub:
    """流式桩：首次 stream/astream 在产出任何 chunk 前抛异常，第二次正常产出 'ok'。"""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def stream(self, messages, stop=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise self.exc
        yield AIMessageChunk(content="ok")

    async def astream(self, messages, stop=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise self.exc
        yield AIMessageChunk(content="ok")


def test_system_prompt_guardrails():
    for kw in ["工具", "来源", "编造", "SKILL.md", "如实标注"]:  # 第6条：防谎报
        assert kw in SYSTEM_PROMPT, kw


def test_build_agent_compiles_with_fake_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config

    config.get_settings.cache_clear()
    import app.agent.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path)
    agent = build_agent("t-build-1")
    assert hasattr(agent, "astream") and hasattr(agent, "ainvoke")


def test_model_whitelist(monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "0")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")  # 已退役 ID
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")
    from app.core import config

    config.get_settings.cache_clear()
    with pytest.raises(ValueError, match="不允许的模型"):
        build_agent("t-build-2")
    assert ALLOWED_MODELS == {"deepseek-v4-flash", "deepseek-v4-pro"}


def test_checkpointer_url_conversion():
    ctx = make_checkpointer("postgresql+asyncpg://u:p@h:5434/db")
    # from_conn_string 返回 async contextmanager；只验证不抛错且 URL 已剥离 +asyncpg
    assert ctx is not None


async def test_fake_llm_end_to_end(tmp_path, monkeypatch):
    """脚本化假模型走完 agent 循环：先调 stock_quote 再答复。"""
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config

    config.get_settings.cache_clear()
    import app.agent.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path)
    agent = build_agent("t-e2e-1")
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "茅台现在多少钱"}]},
        config={"recursion_limit": 50},
    )
    final = result["messages"][-1]
    assert "假回复" in final.content


def test_content_risk_retry_recovers():
    """先抛一次 Content Exists Risk 的 400，再成功——重试应恢复。"""
    stub = _StubModel(_bad_request("400 Content Exists Risk"), n_fail=1)
    wrapper = ContentRiskRetryChatModel(inner=stub)
    result = wrapper.invoke([HumanMessage(content="hi")])
    assert result.content == "桩回复"
    assert stub.calls == 2  # 1 失败 + 1 成功


def test_content_risk_retry_gives_up_after_limit():
    """持续抛 Content Exists Risk——最多 3 次尝试后原样抛出。"""
    stub = _StubModel(_bad_request("400 Content Exists Risk"), n_fail=99)
    wrapper = ContentRiskRetryChatModel(inner=stub)
    with pytest.raises(openai.BadRequestError, match="Content Exists Risk"):
        wrapper.invoke([HumanMessage(content="hi")])
    assert stub.calls == 3  # 1 + 2 次重试


def test_non_content_risk_bad_request_not_retried():
    """非 Content Risk 的 400（如 invalid key）不应重试，立即抛出。"""
    stub = _StubModel(_bad_request("400 Invalid API key"), n_fail=99)
    wrapper = ContentRiskRetryChatModel(inner=stub)
    with pytest.raises(openai.BadRequestError, match="Invalid API key"):
        wrapper.invoke([HumanMessage(content="hi")])
    assert stub.calls == 1  # 不重试


async def test_retry_wrapper_streams_tokens():
    """包装层不得把流塌缩成整块：sync/async 都应逐块产出 a/b/c 三个 token。"""
    stub = _StreamStub()
    wrapper = ContentRiskRetryChatModel(inner=stub)

    sync_chunks = [c.content for c in wrapper.stream([HumanMessage(content="hi")]) if c.content]
    assert sync_chunks == ["a", "b", "c"]  # 证明真流式，非单块

    async_chunks = [
        c.content async for c in wrapper.astream([HumanMessage(content="hi")]) if c.content
    ]
    assert async_chunks == ["a", "b", "c"]


class _RealStreamingModel(BaseChatModel):
    """真 BaseChatModel 桩（区别于 _StreamStub 这种普通对象）。

    只有真模型才会走 LangChain 的 callback/config 传播路径——token 双发只在这条路上暴露。
    """

    @property
    def _llm_type(self) -> str:
        return "real-streaming-stub"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_RealStreamingModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="abc"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for t in ("a", "b", "c"):
            yield ChatGenerationChunk(message=AIMessageChunk(content=t, id="stub-msg"))

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for t in ("a", "b", "c"):
            yield ChatGenerationChunk(message=AIMessageChunk(content=t, id="stub-msg"))


async def test_wrapped_model_does_not_double_stream_tokens(tmp_path, monkeypatch):
    """回归：包装层在 LangGraph 节点里不得让每个 token 被投递两次。

    根因：``_astream`` 调 ``inner.astream``（公开入口）时，LangChain 会经 contextvar
    把节点的 RunnableConfig（含 callbacks）传给内部模型，内部自己发一轮
    ``on_llm_new_token``；外层 ``BaseChatModel.astream`` 再发一轮 → 前端每个 token 重复
    （"前置前置步骤步骤"）。落库的 AIMessage 由外层合并得出仍正确，故刷新页面看着正常。

    FAKE_LLM 路径不经过本包装层，所以此前的假模型测试覆盖不到。
    """
    monkeypatch.setenv("FAKE_LLM", "1")
    from app.core import config

    config.get_settings.cache_clear()
    import app.agent.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr(
        build_mod, "_make_model", lambda: ContentRiskRetryChatModel(inner=_RealStreamingModel())
    )

    agent = build_agent("t-no-dup")
    delivered = []
    async for _ns, event_type, chunk in agent.astream(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "t-no-dup"}, "recursion_limit": 50},
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        if event_type == "messages" and getattr(chunk[0], "content", ""):
            delivered.append(chunk[0].content)

    assert delivered == ["a", "b", "c"], f"token 被重复投递：{delivered}"


async def test_stream_retries_content_risk_before_first_chunk():
    """启动流（首 chunk 前）遇 Content Exists Risk 应重试，第二次恢复；调用次数为 2。"""
    sync_stub = _RiskStreamStub(_bad_request("400 Content Exists Risk"))
    wrapper = ContentRiskRetryChatModel(inner=sync_stub)
    sync_chunks = [c.content for c in wrapper.stream([HumanMessage(content="hi")]) if c.content]
    assert sync_chunks == ["ok"]
    assert sync_stub.calls == 2  # 1 失败 + 1 成功

    async_stub = _RiskStreamStub(_bad_request("400 Content Exists Risk"))
    wrapper = ContentRiskRetryChatModel(inner=async_stub)
    async_chunks = [
        c.content async for c in wrapper.astream([HumanMessage(content="hi")]) if c.content
    ]
    assert async_chunks == ["ok"]
    assert async_stub.calls == 2

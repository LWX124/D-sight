"""Agent 组装：模型选择（Fake / ChatDeepSeek + 白名单 + Content Risk 重试）、
SandboxedFilesystemBackend、skills、五工具、SYSTEM_PROMPT（PoC 五条 + 第6条防谎报 +
日期注入）、Postgres checkpointer 工厂。

## 实证结论（deepagents 0.6.12）

- ``create_deep_agent`` 的签名**直接接受** ``checkpointer: None | bool |
  BaseCheckpointSaver = None``（返回值即已 compile 的 CompiledStateGraph），
  故 ``build_agent`` 把 checkpointer 透传即可，无需额外 ``.compile()``。

- Content Exists Risk 是 DeepSeek 的 **400**，经 langchain-deepseek(1.1.0) →
  openai SDK 抛出 ``openai.BadRequestError``。``Runnable.with_retry`` 的
  ``retry_if_exception_type`` **只接受类型元组**，无法按消息内容过滤——而 400
  下大量非内容风险错误（无效 key、参数错误）绝不能重试。因此改用自定义包装
  ``ContentRiskRetryChatModel``：仅当 ``"Content Exists Risk" in str(e)`` 时重试
  （共 3 次尝试 = 1 + 2），其余 BadRequestError 原样抛出。
"""

import datetime as dt
from collections.abc import AsyncIterator, Iterator
from typing import Any

import openai
from deepagents import create_deep_agent
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_deepseek import ChatDeepSeek

from app.agent.fake_llm import FakeToolCallingModel
from app.agent.tools.runner import make_run_python
from app.agent.tools.stock import stock_financials, stock_quote
from app.agent.tools.web import fetch_page, web_search
from app.agent.workspace import get_thread_workspace, make_backend
from app.core.config import get_settings

ALLOWED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}

_CONTENT_RISK_MARKER = "Content Exists Risk"
_MAX_ATTEMPTS = 3  # 1 次原始 + 2 次重试

SYSTEM_PROMPT = """你是 D-sight 投研助手，服务中文投资者。

硬性规则：
1. 涉及行情、财务、新闻的事实，必须实际调用工具获取，禁止凭记忆编造数字。
2. 报告中的关键数字必须注明来源（工具名或 URL）。
3. 任务匹配某个 skill 描述时，先读入该 skill 的 SKILL.md 并严格按其步骤执行；\
skill 指定的交叉验证步骤（如 tools/financial_rigor.py、tools/report_audit.py）必须用 run_python 真实执行。
4. 简单概念问答（不涉及具体标的的实时数据）直接回答，不要启动重型研究流程。
5. 信息不足或数据不存在时（如未发布的财报），明确说明，不得编造。
6. todo 与结论必须如实标注执行结果：任何审计/验证步骤失败或未执行时，\
必须如实标注"未完成"并在答复中明确说明，严禁将失败步骤标记为完成。
"""


def _is_content_risk(exc: BaseException) -> bool:
    return isinstance(exc, openai.BadRequestError) and _CONTENT_RISK_MARKER in str(exc)


def _to_gen_chunk(chunk: Any) -> ChatGenerationChunk:
    """内部 stream 产出 ``AIMessageChunk``（消息级）时包成 ``ChatGenerationChunk``；
    若已是 ``ChatGenerationChunk`` 则原样返回。"""
    if isinstance(chunk, ChatGenerationChunk):
        return chunk
    return ChatGenerationChunk(message=chunk)


class ContentRiskRetryChatModel(BaseChatModel):
    """包一层：仅对 DeepSeek "Content Exists Risk"（400）重试，其余错误直抛。

    ``bind_tools`` 把工具绑到内部模型上并返回同类包装，使 deepagents 通过
    ``bind_tools(...).invoke/ainvoke`` 调用时，本重试逻辑仍在生效路径上。
    """

    inner: Any = None

    @property
    def _llm_type(self) -> str:
        return "content-risk-retry"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ContentRiskRetryChatModel":
        return ContentRiskRetryChatModel(inner=self.inner.bind_tools(tools, **kwargs))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                msg = self.inner.invoke(messages, stop=stop, **kwargs)
                break
            except openai.BadRequestError as exc:
                if _is_content_risk(exc) and attempt < _MAX_ATTEMPTS:
                    continue
                raise
        if not isinstance(msg, AIMessage):
            msg = AIMessage(content=getattr(msg, "content", str(msg)))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                msg = await self.inner.ainvoke(messages, stop=stop, **kwargs)
                break
            except openai.BadRequestError as exc:
                if _is_content_risk(exc) and attempt < _MAX_ATTEMPTS:
                    continue
                raise
        if not isinstance(msg, AIMessage):
            msg = AIMessage(content=getattr(msg, "content", str(msg)))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """真流式：逐块透传内部模型的 token（不再塌缩成整块），保留 Content Risk 重试。

        委托给 ``self.inner.stream``（而非 ``self.inner._stream``）——因为经
        ``bind_tools`` 后 inner 是 ``_ChatModelBinding``，只有 ``.stream`` 会把绑定的
        ``tools`` 并入调用；``.stream`` 产出消息级 ``AIMessageChunk``，这里包成
        ``ChatGenerationChunk`` 交回 ``BaseChatModel.stream``，由其统一触发
        ``on_llm_new_token``（即 T5 的 ``stream_mode="messages"`` 数据源）。故**不**把
        callbacks 转发给内部 stream，否则会向同一 handler 重复发 token。

        **重试契约**：仅当"启动流、产出第一个 chunk 之前"抛出 Content Exists Risk
        （400）时重试（共 3 次尝试）；一旦已产出任何 chunk 便无法回撤，后续错误直接抛出。
        非 Content Risk 的 400 立即抛出。
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            started = False
            try:
                for chunk in self.inner.stream(messages, stop=stop, **kwargs):
                    started = True
                    yield _to_gen_chunk(chunk)
            except openai.BadRequestError as exc:
                if not started and _is_content_risk(exc) and attempt < _MAX_ATTEMPTS:
                    continue
                raise
            return

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """``_stream`` 的异步版，重试契约与其一致（详见 ``_stream`` docstring）。"""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            started = False
            try:
                async for chunk in self.inner.astream(messages, stop=stop, **kwargs):
                    started = True
                    yield _to_gen_chunk(chunk)
            except openai.BadRequestError as exc:
                if not started and _is_content_risk(exc) and attempt < _MAX_ATTEMPTS:
                    continue
                raise
            return


def _make_model():
    s = get_settings()
    if s.fake_llm:
        return FakeToolCallingModel()
    name = s.deepseek_model
    if name not in ALLOWED_MODELS:
        raise ValueError(f"不允许的模型 ID：{name}，只能用 {sorted(ALLOWED_MODELS)}")
    model = ChatDeepSeek(model=name, api_key=s.deepseek_api_key, timeout=120, max_retries=3)
    return ContentRiskRetryChatModel(inner=model)


def make_checkpointer(database_url: str):
    """返回 ``AsyncPostgresSaver.from_conn_string`` 的 async context（调用方负责 .setup()）。

    SQLAlchemy 的 ``postgresql+asyncpg://`` DSN 需剥离 ``+asyncpg`` 才能给
    psycopg 用的 langgraph checkpointer。
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    return AsyncPostgresSaver.from_conn_string(url)


def build_agent(thread_id: str, checkpointer=None, skill_rows=None, kb_ids=None, user_id=None):
    ws = get_thread_workspace(thread_id)
    if skill_rows is not None:
        from app.skills.materialize import write_skills

        write_skills(ws, skill_rows)
    # 新 workspace 不再全量拷贝 skills；无条件建空目录（幂等），
    # 使 skill_rows=None 的直连调用（test_real_smoke 等）也能组装。
    (ws / "skills").mkdir(exist_ok=True)
    prompt = SYSTEM_PROMPT + f"\n当前日期：{dt.date.today().isoformat()}（做时效判断时以此为准）"
    tools = [web_search, fetch_page, stock_quote, stock_financials, make_run_python(ws)]
    if kb_ids and user_id is not None:
        from app.agent.tools.kb import make_kb_search
        from app.core.db import get_sessionmaker

        tools.append(make_kb_search(get_sessionmaker(), user_id, kb_ids))
    return create_deep_agent(
        model=_make_model(),
        tools=tools,
        backend=make_backend(ws),
        skills=[str(ws / "skills")],
        system_prompt=prompt,
        checkpointer=checkpointer,
    )

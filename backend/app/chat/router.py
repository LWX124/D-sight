import asyncio
import logging
import uuid
from datetime import UTC, datetime

from assistant_stream import RunController, create_run
from assistant_stream.modules.langgraph import append_langgraph_event
from assistant_stream.serialization import DataStreamResponse
from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.build import build_agent
from app.auth.deps import get_current_user
from app.auth.models import User
from app.chat.schemas import ChatRequest
from app.core.config import get_settings
from app.core.db import get_db, get_sessionmaker
from app.credits import service
from app.credits.pricing import tokens_to_credits
from app.threads.models import Thread

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

TITLE_MAX = 30


async def _owned_thread(db: AsyncSession, user: User, thread_id: str | None) -> Thread:
    if not thread_id:
        raise HTTPException(404, "会话不存在")
    try:
        tid = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(404, "会话不存在")
    t = await db.get(Thread, tid)
    if t is None or t.user_id != user.id or t.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return t


def _extract_inputs(request: ChatRequest) -> tuple[list, str]:
    """commands → langchain 消息列表 + 首条文本（供标题）。"""
    messages: list = []
    first_text = ""
    for command in request.commands:
        if command.type == "add-message":
            texts = [p.text for p in command.message.parts if p.type == "text" and p.text]
            if texts:
                joined = " ".join(texts)
                first_text = first_text or joined
                messages.append(HumanMessage(content=joined))
        elif command.type == "add-tool-result":
            content = command.model_content if command.model_content is not None else command.result
            messages.append(
                ToolMessage(
                    content=content if isinstance(content, str) else str(content),
                    tool_call_id=command.tool_call_id,
                    status="error" if command.is_error else "success",
                )
            )
    return messages, first_text


@router.post("")
async def chat(
    request: ChatRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    thread = await _owned_thread(db, user, request.thread_id)
    try:
        await service.precheck(db, user.id, need=get_settings().min_charge)
    except service.InsufficientCredits:
        raise HTTPException(402, "积分不足")
    input_messages, first_text = _extract_inputs(request)
    if thread.title == "新对话" and first_text:
        thread.title = first_text[:TITLE_MAX]
    await db.commit()

    thread_id = str(thread.id)
    checkpointer = getattr(http_request.app.state, "checkpointer", None)
    agent = build_agent(thread_id, checkpointer)

    async def run_callback(controller: RunController):
        if controller.state is None:
            controller.state = {}
        controller.state.setdefault("messages", [])
        for m in input_messages:
            controller.state["messages"].append(m.model_dump())

        usage_cb = UsageMetadataCallbackHandler()
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 200,
            "callbacks": [usage_cb],
        }
        try:
            async with asyncio.timeout(900):  # 15 分钟绝对超时
                async for namespace, event_type, chunk in agent.astream(
                    {"messages": input_messages},
                    config=config,
                    stream_mode=["messages", "updates"],
                    subgraphs=True,
                ):
                    append_langgraph_event(controller.state, namespace, event_type, chunk)
        except TimeoutError:
            # 超时不注入错误事件（断言不依赖其文本）；仍走 finally 按已计量 token 实扣。
            logger.warning("chat run timed out after 900s (thread=%s), charging metered tokens", thread_id)
        finally:
            # 结束扣费 + touch updated_at 合并为一次事务（不复用请求级 session）。
            # updated_at 显式赋值以确保 SQLAlchemy 产生 UPDATE（同值 title 赋值不会标脏）。
            total = sum(v.get("total_tokens", 0) for v in usage_cb.usage_metadata.values())
            async with get_sessionmaker()() as s:
                await service.charge(
                    s, user.id, tokens_to_credits(total),
                    kind="chat", ref_type="thread", ref_id=thread_id,
                )
                t = await s.get(Thread, thread.id)
                if t is not None:
                    t.updated_at = datetime.now(UTC)
                await s.commit()

    return DataStreamResponse(create_run(run_callback, state=request.state))

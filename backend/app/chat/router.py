import uuid
from datetime import UTC, datetime

from assistant_stream import RunController, create_run
from assistant_stream.modules.langgraph import append_langgraph_event
from assistant_stream.serialization import DataStreamResponse
from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.build import build_agent
from app.auth.deps import get_current_user
from app.auth.models import User
from app.chat.schemas import ChatRequest
from app.core.db import get_db, get_sessionmaker
from app.threads.models import Thread

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

        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 200}
        async for namespace, event_type, chunk in agent.astream(
            {"messages": input_messages},
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            append_langgraph_event(controller.state, namespace, event_type, chunk)

        # 运行结束后 touch updated_at：显式赋值以确保 SQLAlchemy 产生 UPDATE
        # （同值 title 赋值不会标脏，无法触发 onupdate）。流回调不复用请求级 session。
        async with get_sessionmaker()() as s:
            t = await s.get(Thread, thread.id)
            if t is not None:
                t.updated_at = datetime.now(UTC)
                await s.commit()

    return DataStreamResponse(create_run(run_callback, state=request.state))

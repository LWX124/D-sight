import asyncio
import logging
import math
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
    from app.core.ratelimit import check_rate

    if not await check_rate(str(user.id)):
        raise HTTPException(429, "请求过于频繁")
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
    from app.skills.materialize import load_installed_skills

    skill_rows = await load_installed_skills(db, user.id)
    mounted: list[uuid.UUID] = []
    for x in (request.mounted_kb_ids or []):
        try:
            mounted.append(uuid.UUID(x))
        except ValueError:
            pass
    agent = build_agent(
        thread_id, checkpointer, skill_rows=skill_rows, kb_ids=mounted, user_id=user.id
    )

    async def run_callback(controller: RunController):
        if controller.state is None:
            controller.state = {}
        controller.state.setdefault("messages", [])
        for m in input_messages:
            controller.state["messages"].append(m.model_dump())
        # 客户端每轮回传累积态：本轮之前的消息（含历史 read_file）不得重复计费。
        baseline = len(controller.state["messages"])

        usage_cb = UsageMetadataCallbackHandler()
        ok = False
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
            ok = True  # 流正常跑完：保留 MIN_CHARGE 下限
        except TimeoutError:
            # 超时视为已交付部分服务（"失败按实际消耗扣"仍走 MIN_CHARGE 下限）；不注入错误事件。
            ok = True
            logger.warning("chat run timed out after 900s (thread=%s), charging metered tokens", thread_id)
        finally:
            # 结束扣费 + touch updated_at 合并为一次事务（不复用请求级 session）。
            # 硬失败（未交付任何服务）按已计量 token 实扣：0 token → 不扣费、不写交易行。
            # 成功/超时后交付：保留 MIN_CHARGE 下限。updated_at 无论是否扣费都必须推进。
            total = sum(v.get("total_tokens", 0) for v in usage_cb.usage_metadata.values())
            credits_due = (
                tokens_to_credits(total)
                if ok
                else math.ceil(max(0, total) / get_settings().tokens_per_credit)
            )
            async with get_sessionmaker()() as s:
                if credits_due > 0:
                    await service.charge(
                        s, user.id, credits_due,
                        kind="chat", ref_type="thread", ref_id=thread_id,
                    )
                # 失败运行（ok=False）也按已读 skill 扣：skill 内容已消费。
                from app.skills.usage import extract_used_skills

                # 仅对本轮新增消息计费；且只有本轮实际物化的 skill 才可扣（越权/幻觉读不计费）。
                # controller.state 是 StateProxy 不支持切片，先物化为普通 list（迭代即取底层 dict）。
                all_msgs = list(controller.state.get("messages") or [])
                used = extract_used_skills(all_msgs[baseline:])
                used &= {r.slug for r in skill_rows}
                if used:
                    from sqlalchemy import select as _select

                    from app.skills.models import Skill

                    rows = (await s.execute(
                        _select(Skill).where(Skill.slug.in_(used), Skill.price > 0)
                    )).scalars().all()
                    for skill_row in rows:
                        await service.charge(
                            s, user.id, skill_row.price,
                            kind="skill", ref_type="skill", ref_id=skill_row.slug,
                        )
                t = await s.get(Thread, thread.id)
                if t is not None:
                    t.updated_at = datetime.now(UTC)
                await s.commit()

    return DataStreamResponse(create_run(run_callback, state=request.state))

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.chat.history import load_thread_messages
from app.core.db import get_db
from app.threads.models import Thread
from app.threads.schemas import ThreadCreateIn, ThreadOut, ThreadPatchIn

router = APIRouter(prefix="/api/threads", tags=["threads"])


def _out(t: Thread) -> ThreadOut:
    return ThreadOut(id=str(t.id), title=t.title, created_at=t.created_at, updated_at=t.updated_at)


async def _owned_thread(db: AsyncSession, user: User, thread_id: str) -> Thread:
    try:
        tid = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(404, "会话不存在")
    t = await db.get(Thread, tid)
    if t is None or t.user_id != user.id or t.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return t


@router.post("/", status_code=201)
async def create_thread(
    body: ThreadCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    t = Thread(user_id=user.id, title=body.title or "新对话")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _out(t)


@router.get("/")
async def list_threads(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ThreadOut]:
    rows = await db.scalars(
        select(Thread)
        .where(
            Thread.user_id == user.id,
            Thread.deleted_at.is_(None),
            Thread.type == "chat",
        )
        .order_by(Thread.updated_at.desc())
    )
    return [_out(t) for t in rows]


@router.get("/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """刷新后恢复聊天：读该 thread 最新 checkpoint 的 human/ai 文本轮。

    归属校验复用 _owned_thread（非本人/已删/非法 id → 404）。checkpointer 从
    app.state 取（未跑 lifespan 的进程为 None → 空历史，本就无跨会话历史）。
    """
    thread = await _owned_thread(db, user, thread_id)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    # 用规范化 id（str(thread.id)）查 checkpointer/工作区，避免大小写/urn 变体
    # 造成空历史或多余工作区目录（chat 端点同样规范化）。
    messages = await load_thread_messages(str(thread.id), checkpointer)
    return {"messages": messages}


@router.patch("/{thread_id}")
async def rename_thread(
    thread_id: str,
    body: ThreadPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    t = await _owned_thread(db, user, thread_id)
    t.title = body.title
    await db.commit()
    await db.refresh(t)
    return _out(t)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    t = await _owned_thread(db, user, thread_id)
    t.deleted_at = dt.datetime.now(dt.UTC)
    await db.commit()

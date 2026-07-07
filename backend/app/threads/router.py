import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
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
        .where(Thread.user_id == user.id, Thread.deleted_at.is_(None))
        .order_by(Thread.updated_at.desc())
    )
    return [_out(t) for t in rows]


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

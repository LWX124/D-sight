"""Phase 4: 收藏路由。

- POST   /api/social/bookmarks              — 收藏内容
- DELETE /api/social/bookmarks/{item_id}     — 取消收藏
- GET    /api/social/bookmarks              — 列出收藏
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.social.bookmarks import bookmark_item, list_bookmarks, unbookmark_item
from app.social.schemas import BookmarkIn

router = APIRouter(tags=["social-bookmarks"])


@router.post("/bookmarks")
async def add_bookmark(
    body: BookmarkIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """收藏内容。"""
    try:
        bookmark = await bookmark_item(db, user.id, body.item_id, body.notes)
        await db.commit()
        return {"id": str(bookmark.id), "item_id": str(body.item_id), "ok": True}
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.delete("/bookmarks/{item_id}")
async def remove_bookmark(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消收藏。"""
    ok = await unbookmark_item(db, user.id, item_id)
    if not ok:
        raise HTTPException(404, "收藏不存在")
    await db.commit()
    return {"ok": True}


@router.get("/bookmarks")
async def get_bookmarks(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出收藏。"""
    return await list_bookmarks(db, user.id, limit)

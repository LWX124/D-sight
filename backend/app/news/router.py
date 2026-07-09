import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.news.models import NewsItem
from app.news.schemas import NewsItemOut

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/thread")
async def get_news_thread(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.threads.models import Thread
    result = await db.execute(
        select(Thread).where(
            Thread.user_id == user.id,
            Thread.type == "news",
            Thread.deleted_at.is_(None),
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        thread = Thread(user_id=user.id, title="新闻助手", type="news")
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return {"thread_id": str(thread.id)}


@router.get("", response_model=list[NewsItemOut])
async def list_news(
    channel: str = "news",
    limit: int = Query(20, ge=1, le=50),
    before: dt.datetime | None = None,
    after: dt.datetime | None = None,
    keyword: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(NewsItem).where(NewsItem.channel == channel)
    if before is not None:
        q = q.where(NewsItem.published_at < before)
    if after is not None:
        q = q.where(NewsItem.published_at > after)
    if keyword:
        q = q.where(
            NewsItem.content.ilike(f"%{keyword}%") | NewsItem.title.ilike(f"%{keyword}%")
        )
    q = q.order_by(NewsItem.published_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [
        {"id": str(r.id), "channel": r.channel, "title": r.title, "content": r.content,
         "url": r.url, "published_at": r.published_at.isoformat()}
        for r in rows
    ]


@router.post("/refresh", response_model=list[NewsItemOut])
async def refresh_news(
    channel: str = "news",
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.news.ingest import ingest_source
    from app.news.models import NewsSource

    sources = (await db.execute(
        select(NewsSource).where(NewsSource.enabled.is_(True), NewsSource.channel == channel)
    )).scalars().all()
    for source in sources:
        await ingest_source(db, source)

    q = (select(NewsItem).where(NewsItem.channel == channel)
         .order_by(NewsItem.published_at.desc()).limit(limit))
    rows = (await db.execute(q)).scalars().all()
    return [
        {"id": str(r.id), "channel": r.channel, "title": r.title, "content": r.content,
         "url": r.url, "published_at": r.published_at.isoformat()}
        for r in rows
    ]

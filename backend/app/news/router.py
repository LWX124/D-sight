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


@router.get("", response_model=list[NewsItemOut])
async def list_news(
    channel: str = "news",
    limit: int = Query(20, ge=1, le=50),
    before: dt.datetime | None = None,
    after: dt.datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(NewsItem).where(NewsItem.channel == channel)
    if before is not None:
        q = q.where(NewsItem.published_at < before)
    if after is not None:
        q = q.where(NewsItem.published_at > after)
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

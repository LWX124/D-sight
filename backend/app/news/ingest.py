import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.news.models import NewsItem, NewsSource as NewsSourceRow
from app.news.sources import content_hash, get_source

_log = logging.getLogger(__name__)


async def ingest_source(db: AsyncSession, source: NewsSourceRow) -> int:
    impl = get_source(source.type)
    items = await impl.fetch(source.config or {})
    added = 0
    for raw in items:
        exists = (await db.execute(
            select(NewsItem.id).where(
                NewsItem.source_id == source.id, NewsItem.external_id == raw.external_id
            )
        )).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(NewsItem(
            source_id=source.id, channel=source.channel, external_id=raw.external_id,
            content_hash=content_hash(raw.content), title=raw.title, content=raw.content,
            url=raw.url, published_at=raw.published_at,
        ))
        added += 1
    await db.commit()
    return added

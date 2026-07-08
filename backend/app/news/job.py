import logging

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.news.ingest import ingest_source
from app.news.models import NewsSource

_log = logging.getLogger(__name__)


async def poll_all_sources() -> int:
    total = 0
    async with get_sessionmaker()() as db:
        sources = (await db.execute(
            select(NewsSource).where(NewsSource.enabled.is_(True))
        )).scalars().all()
    for source in sources:
        try:
            async with get_sessionmaker()() as db:
                s = await db.get(NewsSource, source.id)
                total += await ingest_source(db, s)
        except Exception:  # noqa: BLE001 — 单信源失败隔离
            _log.exception("news poll failed for source %s", source.id)
    return total

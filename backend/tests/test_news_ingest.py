import datetime as dt

import pytest
from sqlalchemy import func, select

from app.news.ingest import ingest_source
from app.news.models import NewsItem, NewsSource


async def _fake_source(db, items=None):
    s = NewsSource(name="fake", type="fake", channel="news", config={"items": items} if items else {})
    db.add(s)
    await db.commit()
    return s


@pytest.mark.asyncio
async def test_ingest_inserts_and_dedups(db_session):
    s = await _fake_source(db_session)
    n1 = await ingest_source(db_session, s)
    assert n1 == 2  # FakeSource 默认 2 条
    n2 = await ingest_source(db_session, s)  # 再拉同样 2 条 → 全去重
    assert n2 == 0
    total = (await db_session.execute(
        select(func.count()).select_from(NewsItem).where(NewsItem.source_id == s.id)
    )).scalar_one()
    assert total == 2


@pytest.mark.asyncio
async def test_ingest_custom_items(db_session):
    now = dt.datetime.now(dt.UTC)
    items = [{"external_id": "x1", "content": "自定义快讯", "published_at": now.isoformat()}]
    s = await _fake_source(db_session, items=items)
    assert await ingest_source(db_session, s) == 1
    row = (await db_session.execute(
        select(NewsItem).where(NewsItem.external_id == "x1")
    )).scalar_one()
    assert row.content == "自定义快讯" and len(row.content_hash) == 64

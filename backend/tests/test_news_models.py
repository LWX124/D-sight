import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from app.news.models import NewsItem, NewsSource


async def _source(db):
    s = NewsSource(name="新浪快讯", type="sina_live", channel="news", config={})
    db.add(s)
    await db.flush()
    return s


@pytest.mark.asyncio
async def test_item_roundtrip(db_session):
    s = await _source(db_session)
    item = NewsItem(
        source_id=s.id, channel="news", external_id="e1", content_hash="h1",
        content="快讯正文", published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(item)
    await db_session.commit()
    got = await db_session.get(NewsItem, item.id)
    assert got.external_id == "e1" and got.channel == "news"


@pytest.mark.asyncio
async def test_duplicate_external_id_rejected(db_session):
    s = await _source(db_session)
    now = dt.datetime.now(dt.UTC)
    db_session.add(NewsItem(source_id=s.id, channel="news", external_id="dup",
                            content_hash="h", content="a", published_at=now))
    await db_session.flush()
    db_session.add(NewsItem(source_id=s.id, channel="news", external_id="dup",
                            content_hash="h2", content="b", published_at=now))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

import pytest
from sqlalchemy import func, select

from app.news.job import poll_all_sources
from app.news.models import NewsItem, NewsSource


@pytest.mark.asyncio
async def test_poll_ingests_enabled_only(db_session):
    db_session.add(NewsSource(name="on", type="fake", channel="news", config={}, enabled=True))
    db_session.add(NewsSource(name="off", type="fake", channel="news", config={}, enabled=False))
    await db_session.commit()
    added = await poll_all_sources()
    assert added >= 2  # 启用的 fake 源产 2 条；禁用的不产
    # 禁用源无 item
    off = (await db_session.execute(select(NewsSource).where(NewsSource.name == "off"))).scalar_one()
    n = (await db_session.execute(
        select(func.count()).select_from(NewsItem).where(NewsItem.source_id == off.id)
    )).scalar_one()
    assert n == 0

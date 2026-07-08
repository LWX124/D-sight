import datetime as dt
import uuid

import pytest

from app.agent.tools.news import make_news_query
from app.core.db import get_sessionmaker
from app.news.models import NewsItem, NewsSource


@pytest.mark.asyncio
async def test_news_query_filters_keyword_and_window(db_session):
    s = NewsSource(name=f"s-{uuid.uuid4()}", type="fake", channel="news", config={})
    db_session.add(s)
    await db_session.flush()
    now = dt.datetime.now(dt.UTC)
    db_session.add_all([
        NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-a", content_hash="a",
                 content="茅台大涨", published_at=now),
        NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-b", content_hash="b",
                 content="宁德时代发布", published_at=now),
        NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-c", content_hash="c",
                 content="茅台旧闻", published_at=now - dt.timedelta(hours=48)),
    ])
    await db_session.commit()
    tool = make_news_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "茅台", "hours": 24})
    assert "茅台大涨" in out and "茅台旧闻" not in out and "宁德时代" not in out


@pytest.mark.asyncio
async def test_news_query_empty_window(db_session):
    tool = make_news_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "不存在的关键词xyz", "hours": 1})
    assert "无相关快讯" in out

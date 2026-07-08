import datetime as dt
import os

import pytest

from app.agent.tools.news import make_news_query
from app.core.db import get_sessionmaker
from app.news.job import poll_all_sources
from app.news.models import NewsSource
from app.news.sources import SinaLiveSource


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.mark.asyncio
async def test_source_to_feed_to_tool(client, db_session, registered_user):
    # published_at 在 config(JSONB) 里必须是 ISO 字符串——JSONB 无法序列化 datetime，
    # FakeSource.fetch 会把 str 反解成 datetime。
    now_iso = dt.datetime.now(dt.UTC).isoformat()
    db_session.add(NewsSource(
        name="flow", type="fake", channel="news",
        config={"items": [{"external_id": "f1", "content": "茅台快讯闭环", "published_at": now_iso}]},
    ))
    await db_session.commit()

    added = await poll_all_sources()
    assert added >= 1

    feed = (await client.get("/api/news?channel=news&limit=50", headers=_auth(registered_user))).json()
    assert any(i["content"] == "茅台快讯闭环" for i in feed)

    tool = make_news_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "茅台快讯闭环", "hours": 24})
    assert "茅台快讯闭环" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_limit", [0, -1])
async def test_news_limit_lower_bound_422(client, registered_user, bad_limit):
    # limit 无下界会让 LIMIT -1 打到 Postgres 报 500；ge=1 应在校验层挡为 422。
    r = await client.get(f"/api/news?limit={bad_limit}", headers=_auth(registered_user))
    assert r.status_code == 422


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_NEWS_LIVE") != "1", reason="真实网络抓取，手动 smoke：RUN_NEWS_LIVE=1")
async def test_sina_live_smoke():
    # 手动验证新浪 7x24 真实字段解析；默认跳过、不入 CI（无网络依赖）。
    items = await SinaLiveSource().fetch({})
    assert items and all(i.external_id and i.content for i in items)

import datetime as dt
import uuid

import pytest

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.core.db import get_sessionmaker
from app.social.ingest import get_or_create_account
from app.social.models import WechatArticle


@pytest.mark.asyncio
async def test_wechat_query_returns_matches(db_session):
    acc = await get_or_create_account(db_session, f"TF{uuid.uuid4().hex[:6]}", "投研号")
    db_session.add(WechatArticle(
        account_id=acc.id, external_id=f"q{uuid.uuid4().hex[:6]}", title="茅台深度", digest="估值",
        url="https://mp/s/q1", content="茅台正文分析",
        published_at=dt.datetime.now(dt.UTC),
    ))
    await db_session.commit()

    from app.agent.tools.social import make_wechat_query
    tool = make_wechat_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "茅台", "days": 30})
    assert "茅台深度" in out


@pytest.mark.asyncio
async def test_wechat_query_empty_window():
    from app.agent.tools.social import make_wechat_query
    tool = make_wechat_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "不存在的关键词zzz", "days": 1})
    assert "无" in out or "（" in out

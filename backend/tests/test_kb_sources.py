import datetime as dt
import uuid

import httpx
import pytest

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.kb.sources import (
    SUPPORTED_ITEM_TYPES,
    SourceNotFound,
    describe,
    resolve_text,
)


async def _wechat_article(db, title="茅台年报解读", content=None):
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    acc = await get_or_create_account(db, f"F{uuid.uuid4().hex[:8]}", "财经号")
    art = WechatArticle(
        account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title=title,
        digest="", cover_url=None, url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:6]}",
        content=content, published_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
    )
    db.add(art)
    await db.commit()
    return art


async def _news_item(db, title, content):
    from app.news.models import NewsItem, NewsSource

    src = NewsSource(name="新浪快讯", type="sina_live", channel="news", config={})
    db.add(src)
    await db.flush()
    item = NewsItem(
        source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
        content_hash=uuid.uuid4().hex, title=title, content=content,
        url="https://finance.sina.com.cn/x", published_at=dt.datetime(2026, 7, 2, tzinfo=dt.UTC),
    )
    db.add(item)
    await db.commit()
    return item


def test_supported_item_types():
    assert SUPPORTED_ITEM_TYPES == frozenset({"wechat_article", "news_item"})


@pytest.mark.asyncio
async def test_describe_wechat_article(db_session):
    art = await _wechat_article(db_session)
    meta = await describe(db_session, "wechat_article", str(art.id))
    assert meta.title == "茅台年报解读"
    assert meta.source_url == art.url
    assert meta.published_at == art.published_at


@pytest.mark.asyncio
async def test_describe_news_item_falls_back_to_content_prefix(db_session):
    """快讯 title 可空，为空时取 content 前 40 字加省略号。"""
    long = "一" * 100
    item = await _news_item(db_session, None, long)
    meta = await describe(db_session, "news_item", str(item.id))
    assert meta.title == "一" * 40 + "…"
    assert meta.published_at == item.published_at


@pytest.mark.asyncio
async def test_describe_news_item_uses_title_when_present(db_session):
    item = await _news_item(db_session, "央行降准", "内容若干")
    meta = await describe(db_session, "news_item", str(item.id))
    assert meta.title == "央行降准"


@pytest.mark.asyncio
async def test_describe_raises_for_missing_and_unknown(db_session):
    with pytest.raises(SourceNotFound):
        await describe(db_session, "wechat_article", str(uuid.uuid4()))
    with pytest.raises(SourceNotFound):
        await describe(db_session, "xhs_note", str(uuid.uuid4()))
    # 非法 uuid 也走同一出口，不该冒 ValueError
    with pytest.raises(SourceNotFound):
        await describe(db_session, "news_item", "not-a-uuid")


@pytest.mark.asyncio
async def test_resolve_news_item_reads_local_no_http(db_session):
    item = await _news_item(db_session, "标题", "快讯正文内容")
    assert await resolve_text(db_session, "news_item", str(item.id)) == "快讯正文内容"


@pytest.mark.asyncio
async def test_resolve_wechat_article_uses_cached_content(db_session):
    art = await _wechat_article(db_session, content="已缓存的正文")
    # 没传 http 也能拿到——正文已在库里，不需要回源
    assert await resolve_text(db_session, "wechat_article", str(art.id)) == "已缓存的正文"


@pytest.mark.asyncio
async def test_resolve_wechat_article_fetches_and_persists(db_session):
    art = await _wechat_article(db_session, content=None)
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><body><p>抓来的正文</p></body></html>")
    ))
    text = await resolve_text(db_session, "wechat_article", str(art.id), http=http)
    assert "抓来的正文" in text
    await db_session.refresh(art)
    assert art.content and art.content_fetched_at is not None   # 顺手回填源表

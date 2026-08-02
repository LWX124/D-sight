import asyncio
import datetime as dt
import io
import uuid

import pytest

from app.kb.retrieval import search_chunks
from tests.conftest import _auth


@pytest.fixture
def fast_limiter(monkeypatch):
    """正文抓取限流器置零 + 重置内部状态，避免用例间互相阻塞。"""
    from app.core import config
    from app.kb.ratelimit import reset_for_tests

    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0")
    config.get_settings.cache_clear()
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


@pytest.mark.asyncio
async def test_wechat_article_to_retrieval(client, db_session, registered_user, fast_limiter):
    """闭环：公众号文章 → 加入知识库 → 后台切片 → kb_search 能检索到且带出处。"""
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "社媒库"}, headers=h)).json()["id"]

    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:8]}", "财经号")
    art = WechatArticle(
        account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title="茅台年报解读",
        digest="", cover_url=None, url="https://mp.weixin.qq.com/s/flow",
        content="贵州茅台2025年净利润同比增长，毛利率维持高位。" * 10,
        published_at=dt.datetime(2026, 7, 15, tzinfo=dt.UTC),
    )
    db_session.add(art)
    await db_session.commit()

    r = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "wechat_article", "source_ref_id": str(art.id)}]})).json()
    assert r["added"] == 1

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready", docs[0].get("error")

    hits = await search_chunks(db_session, [uuid.UUID(kb_id)], "茅台 净利润")
    assert hits
    # 出处用 title——社媒文档没有 filename
    assert hits[0]["filename"] == "茅台年报解读"


@pytest.mark.asyncio
async def test_news_item_to_retrieval(client, db_session, registered_user, fast_limiter):
    """闭环：快讯 → 加入知识库 → 后台切片 → kb_search 能检索到且带出处。"""
    from app.news.models import NewsItem, NewsSource

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "快讯库"}, headers=h)).json()["id"]

    src = NewsSource(name="新浪", type="sina_live", channel="news", config={})
    db_session.add(src)
    await db_session.flush()
    item = NewsItem(source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title="央行宣布降准",
                    content="央行决定于下月起下调存款准备金率0.5个百分点。" * 8,
                    url="https://finance.sina.com.cn/flow",
                    published_at=dt.datetime(2026, 7, 16, tzinfo=dt.UTC))
    db_session.add(item)
    await db_session.commit()

    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready"

    hits = await search_chunks(db_session, [uuid.UUID(kb_id)], "降准 存款准备金率")
    assert hits and hits[0]["filename"] == "央行宣布降准"


@pytest.mark.asyncio
async def test_upload_path_still_works(client, registered_user):
    """回归：重构 ingest 后上传路径行为不变，出处仍是文件名。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "上传回归"}, headers=h)).json()["id"]
    files = {"file": ("maotai.txt", io.BytesIO("贵州茅台净利润大幅增长。".encode("utf-8")),
                      "text/plain")}
    assert (await client.post(f"/api/kb/{kb_id}/documents", files=files,
                              headers=h)).status_code == 200
    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if docs and docs[0]["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.1)
    assert docs[0]["status"] == "ready"
    assert docs[0]["filename"] == "maotai.txt" and docs[0]["title"] == "maotai.txt"
    assert docs[0]["source_type"] == "upload"

import asyncio
import datetime as dt
import uuid

import pytest

from tests.conftest import _auth


async def _account_with_articles(db, n=2):
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    acc = await get_or_create_account(db, f"F{uuid.uuid4().hex[:8]}", "财经号")
    for i in range(n):
        db.add(WechatArticle(
            account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title=f"文章{i}",
            digest="", cover_url=None, url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:6]}",
            content="正文内容足够长以便切片。" * 20,
            published_at=dt.datetime(2026, 7, i + 1, tzinfo=dt.UTC),
        ))
    await db.commit()
    return acc


@pytest.fixture
def fast_limiter(monkeypatch):
    from app.core import config
    from app.kb.ratelimit import reset_for_tests

    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0")
    config.get_settings.cache_clear()
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


@pytest.mark.asyncio
async def test_subscribe_account_triggers_backfill(client, db_session, registered_user,
                                                   fast_limiter):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "公众号库"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 2)

    r = await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "财经号"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending" and r.json()["enabled"] is True

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2 and all(d["status"] in ("ready", "failed") for d in docs):
            break
        await asyncio.sleep(0.1)
    assert len(docs) == 2 and all(d["status"] == "ready" for d in docs)
    assert all(d["source_type"] == "wechat_article" for d in docs)

    srcs = (await client.get(f"/api/kb/{kb_id}/sources", headers=h)).json()
    assert len(srcs) == 1 and srcs[0]["status"] == "ready"


@pytest.mark.asyncio
async def test_duplicate_subscribe_returns_existing(client, db_session, registered_user,
                                                    fast_limiter):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "重复订阅"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 1)
    body = {"source_type": "wechat_account", "source_ref_id": str(acc.id),
            "display_name": "财经号"}
    first = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json=body)).json()
    second = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json=body)).json()
    assert first["id"] == second["id"]
    assert len((await client.get(f"/api/kb/{kb_id}/sources", headers=h)).json()) == 1


@pytest.mark.asyncio
async def test_unsupported_source_type_is_400(client, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "x"}, headers=h)).json()["id"]
    r = await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "xhs_user", "source_ref_id": str(uuid.uuid4()), "display_name": "小红书"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unsubscribe_keeps_documents_by_default(client, db_session, registered_user,
                                                     fast_limiter):
    """取消订阅保留已入库文档；清理走显式的 purge。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "保留库"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 2)
    src_id = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "号"})).json()["id"]

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2:
            break
        await asyncio.sleep(0.1)

    r = (await client.delete(f"/api/kb/{kb_id}/sources/{src_id}", headers=h)).json()
    assert r == {"deleted": True, "purged": 0}
    assert len((await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()) == 2


@pytest.mark.asyncio
async def test_unsubscribe_with_purge_deletes_documents(client, db_session, registered_user,
                                                       fast_limiter):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "清理库"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 2)
    src_id = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "号"})).json()["id"]

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2:
            break
        await asyncio.sleep(0.1)

    r = (await client.delete(f"/api/kb/{kb_id}/sources/{src_id}?purge=true", headers=h)).json()
    assert r["deleted"] is True and r["purged"] == 2
    assert (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json() == []


@pytest.mark.asyncio
async def test_purge_spares_manually_added_documents(client, db_session, registered_user,
                                                     fast_limiter):
    """purge 只删该订阅带进来的（kb_source_id 匹配），手动加入的不受影响。"""
    from app.news.models import NewsItem, NewsSource

    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "混合清理"}, headers=h)).json()["id"]
    acc = await _account_with_articles(db_session, 1)
    src_id = (await client.post(f"/api/kb/{kb_id}/sources", headers=h, json={
        "source_type": "wechat_account", "source_ref_id": str(acc.id),
        "display_name": "号"})).json()["id"]

    ns = NewsSource(name="s", type="sina_live", channel="news", config={})
    db_session.add(ns)
    await db_session.flush()
    item = NewsItem(source_id=ns.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title="手动加的快讯", content="内容",
                    url=None, published_at=dt.datetime(2026, 7, 9, tzinfo=dt.UTC))
    db_session.add(item)
    await db_session.commit()
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})

    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
        if len(docs) >= 2:
            break
        await asyncio.sleep(0.1)

    await client.delete(f"/api/kb/{kb_id}/sources/{src_id}?purge=true", headers=h)
    left = (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json()
    assert [d["title"] for d in left] == ["手动加的快讯"]


@pytest.mark.asyncio
async def test_sources_on_foreign_kb_is_404(client, registered_user):
    h = _auth(registered_user)
    assert (await client.get("/api/kb/00000000-0000-0000-0000-000000000000/sources",
                             headers=h)).status_code == 404

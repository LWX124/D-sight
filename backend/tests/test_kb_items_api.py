import asyncio
import datetime as dt
import uuid

import pytest

from tests.conftest import _auth


async def _news_item(db, title="央行降准", content="快讯正文内容够长一点。"):
    from app.news.models import NewsItem, NewsSource

    src = NewsSource(name="s", type="sina_live", channel="news", config={})
    db.add(src)
    await db.flush()
    item = NewsItem(source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title=title, content=content,
                    url="https://finance.sina.com.cn/x",
                    published_at=dt.datetime(2026, 7, 5, tzinfo=dt.UTC))
    db.add(item)
    await db.commit()
    return item


async def _wait_ready(client, kb_id, headers, expect=1):
    for _ in range(60):
        docs = (await client.get(f"/api/kb/{kb_id}/documents", headers=headers)).json()
        if len([d for d in docs if d["status"] in ("ready", "failed")]) >= expect:
            return docs
        await asyncio.sleep(0.1)
    return docs


@pytest.mark.asyncio
async def test_add_item_then_document_becomes_ready(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "快讯库"}, headers=h)).json()["id"]
    item = await _news_item(db_session)

    r = await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    assert r.status_code == 200
    assert r.json() == {"added": 1, "duplicate": 0, "failed": []}

    docs = await _wait_ready(client, kb_id, h)
    assert docs[0]["status"] == "ready"
    assert docs[0]["title"] == "央行降准"
    assert docs[0]["source_type"] == "news_item"
    assert docs[0]["published_at"].startswith("2026-07-05")


@pytest.mark.asyncio
async def test_add_same_item_twice_reports_duplicate(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "去重库"}, headers=h)).json()["id"]
    item = await _news_item(db_session)
    body = {"items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]}
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h, json=body)).json()["added"] == 1
    r2 = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json=body)).json()
    assert r2 == {"added": 0, "duplicate": 1, "failed": []}


@pytest.mark.asyncio
async def test_batch_partial_failure_does_not_block_others(client, db_session, registered_user):
    """单条失败不影响同批其余条目。"""
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "混合库"}, headers=h)).json()["id"]
    ok = await _news_item(db_session)
    missing = str(uuid.uuid4())
    bad_type_ref = str(uuid.uuid4())

    r = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={"items": [
        {"source_type": "news_item", "source_ref_id": str(ok.id)},
        {"source_type": "news_item", "source_ref_id": missing},
        {"source_type": "xhs_note", "source_ref_id": bad_type_ref},
    ]})).json()
    assert r["added"] == 1 and r["duplicate"] == 0
    assert {f["source_ref_id"] for f in r["failed"]} == {missing, bad_type_ref}
    assert all(f["error"] for f in r["failed"])


@pytest.mark.asyncio
async def test_items_rejects_empty_and_oversized_batch(client, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "边界库"}, headers=h)).json()["id"]
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h,
                              json={"items": []})).status_code == 422
    too_many = [{"source_type": "news_item", "source_ref_id": str(uuid.uuid4())} for _ in range(51)]
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h,
                              json={"items": too_many})).status_code == 422


@pytest.mark.asyncio
async def test_items_on_foreign_kb_is_404(client, db_session, registered_user):
    h = _auth(registered_user)
    item = await _news_item(db_session)
    r = await client.post("/api/kb/00000000-0000-0000-0000-000000000000/items", headers=h,
                          json={"items": [{"source_type": "news_item",
                                           "source_ref_id": str(item.id)}]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_document_detail_returns_text_snapshot(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "详情库"}, headers=h)).json()["id"]
    item = await _news_item(db_session, content="这是入库时的文本快照，详情页展示的就是它。")
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    docs = await _wait_ready(client, kb_id, h)
    doc_id = docs[0]["id"]

    d = (await client.get(f"/api/kb/{kb_id}/documents/{doc_id}", headers=h)).json()
    assert d["text"].startswith("这是入库时的文本快照")
    assert d["source_url"] == item.url
    # 他人库 / 不存在的文档 → 404
    assert (await client.get(f"/api/kb/{kb_id}/documents/{uuid.uuid4()}",
                             headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_delete_document(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "删除库"}, headers=h)).json()["id"]
    item = await _news_item(db_session)
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    docs = await _wait_ready(client, kb_id, h)
    doc_id = docs[0]["id"]

    assert (await client.delete(f"/api/kb/{kb_id}/documents/{doc_id}",
                                headers=h)).status_code == 200
    assert (await client.get(f"/api/kb/{kb_id}/documents", headers=h)).json() == []
    # 删过之后可以重新加入（唯一约束随文档一起消失）
    assert (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={
        "items": [{"source_type": "news_item", "source_ref_id": str(item.id)}]})
    ).json()["added"] == 1


@pytest.mark.asyncio
async def test_documents_pagination_and_ordering(client, db_session, registered_user):
    h = _auth(registered_user)
    kb_id = (await client.post("/api/kb", json={"name": "分页库"}, headers=h)).json()["id"]
    items = [await _news_item(db_session, title=f"快讯{i}") for i in range(3)]
    await client.post(f"/api/kb/{kb_id}/items", headers=h, json={"items": [
        {"source_type": "news_item", "source_ref_id": str(i.id)} for i in items]})
    await _wait_ready(client, kb_id, h, expect=3)

    page = (await client.get(f"/api/kb/{kb_id}/documents?limit=2&offset=0", headers=h)).json()
    assert len(page) == 2
    rest = (await client.get(f"/api/kb/{kb_id}/documents?limit=2&offset=2", headers=h)).json()
    assert len(rest) == 1
    assert {d["id"] for d in page}.isdisjoint({d["id"] for d in rest})


@pytest.mark.asyncio
async def test_quota_stops_batch_and_reports_remaining_as_failed(
    client, db_session, registered_user, monkeypatch,
):
    """触顶后中止同批剩余条目：已加入的照数，触顶那条进 failed 带文案。

    配额是花钱/占存储的闸门，这条分支一旦静默失效就没人发现，故单独钉住。
    """
    from app.core import config

    monkeypatch.setenv("KB_MAX_DOCUMENTS_PER_KB", "2")
    config.get_settings.cache_clear()
    try:
        h = _auth(registered_user)
        kb_id = (await client.post("/api/kb", json={"name": "配额库"}, headers=h)).json()["id"]
        items = [await _news_item(db_session, title=f"额{i}") for i in range(4)]

        r = (await client.post(f"/api/kb/{kb_id}/items", headers=h, json={"items": [
            {"source_type": "news_item", "source_ref_id": str(i.id)} for i in items]})).json()
        # 上限 2 → 前两条进库，第三条触顶并中止，第四条根本没试
        assert r["added"] == 2
        assert len(r["failed"]) == 1
        assert "2 篇文档上限" in r["failed"][0]["error"]
        assert r["failed"][0]["source_ref_id"] == str(items[2].id)
    finally:
        config.get_settings.cache_clear()

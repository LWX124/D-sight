import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.kb.models import Kb, KbDocument
from app.kb.service import add_source_item
from app.kb.sources import SourceNotFound


async def _user_kb(db, name="库"):
    u = User(email=f"dd-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name=name)
    db.add(kb)
    await db.commit()
    return u, kb


async def _news_item(db, content="快讯正文"):
    from app.news.models import NewsItem, NewsSource

    src = NewsSource(name="s", type="sina_live", channel="news", config={})
    db.add(src)
    await db.flush()
    item = NewsItem(source_id=src.id, channel="news", external_id=f"n{uuid.uuid4().hex[:8]}",
                    content_hash=uuid.uuid4().hex, title="标题", content=content,
                    url=None, published_at=dt.datetime(2026, 7, 3, tzinfo=dt.UTC))
    db.add(item)
    await db.commit()
    return item


@pytest.mark.asyncio
async def test_add_creates_pending_document_with_meta(db_session):
    _, kb = await _user_kb(db_session)
    item = await _news_item(db_session)
    result, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id))
    assert result == "added" and doc_id is not None
    doc = await db_session.get(KbDocument, doc_id)
    assert doc.status == "pending" and doc.title == "标题"
    assert doc.source_type == "news_item" and doc.source_ref_id == str(item.id)
    assert doc.published_at == item.published_at and doc.filename is None


@pytest.mark.asyncio
async def test_same_item_twice_in_one_kb_is_duplicate(db_session):
    _, kb = await _user_kb(db_session)
    item = await _news_item(db_session)
    assert (await add_source_item(db_session, kb.id, "news_item", str(item.id)))[0] == "added"
    result, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id))
    assert result == "duplicate" and doc_id is None
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
    )).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_same_item_in_two_kbs_stored_separately(db_session):
    """不做全局内容去重：两个库各存一份文档。省的是 embedding 调用，不是 Postgres 存储。"""
    _, kb1 = await _user_kb(db_session, "库1")
    _, kb2 = await _user_kb(db_session, "库2")
    item = await _news_item(db_session)
    assert (await add_source_item(db_session, kb1.id, "news_item", str(item.id)))[0] == "added"
    assert (await add_source_item(db_session, kb2.id, "news_item", str(item.id)))[0] == "added"


@pytest.mark.asyncio
async def test_concurrent_insert_falls_back_to_duplicate(db_session, monkeypatch):
    """并发下「先查后插」有竞态窗口，靠唯一约束兜底 → IntegrityError 转 duplicate。"""
    _, kb = await _user_kb(db_session)
    item = await _news_item(db_session)
    # 先手工插一条绕过 add_source_item 的查重，模拟另一并发请求刚插入
    db_session.add(KbDocument(kb_id=kb.id, title="抢先", source_type="news_item",
                              source_ref_id=str(item.id), status="pending"))
    await db_session.commit()

    from app.kb import service

    async def _no_dup(db, kb_id, source_type, source_ref_id):
        return None                      # 假装查重没查到

    monkeypatch.setattr(service, "_find_existing", _no_dup)
    result, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id))
    assert result == "duplicate" and doc_id is None


@pytest.mark.asyncio
async def test_missing_source_raises(db_session):
    _, kb = await _user_kb(db_session)
    with pytest.raises(SourceNotFound):
        await add_source_item(db_session, kb.id, "news_item", str(uuid.uuid4()))
    with pytest.raises(SourceNotFound):
        await add_source_item(db_session, kb.id, "xhs_note", str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_kb_source_id_is_recorded(db_session):
    """由整号订阅自动入库的文档带 kb_source_id，purge 时据此批量删除。"""
    from app.kb.models import KbSource

    _, kb = await _user_kb(db_session)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(uuid.uuid4()), display_name="号")
    db_session.add(src)
    await db_session.flush()
    item = await _news_item(db_session)
    _, doc_id = await add_source_item(db_session, kb.id, "news_item", str(item.id),
                                      kb_source_id=src.id)
    doc = await db_session.get(KbDocument, doc_id)
    assert doc.kb_source_id == src.id

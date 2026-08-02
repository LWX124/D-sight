import datetime as dt
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core import config
from app.core.security import hash_password
from app.kb.models import Kb, KbDocument, KbSource


@pytest.fixture
def fast_limiter(monkeypatch):
    monkeypatch.setenv("KB_BACKFILL_DELAY_SECONDS", "0")
    config.get_settings.cache_clear()
    from app.kb.ratelimit import reset_for_tests
    reset_for_tests()
    yield
    config.get_settings.cache_clear()
    reset_for_tests()


async def _kb(db):
    u = User(email=f"bf-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    kb = Kb(owner_id=u.id, name="回填库")
    db.add(kb)
    await db.commit()
    return kb


async def _account_with_articles(db, n, content="正文内容"):
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatArticle

    acc = await get_or_create_account(db, f"F{uuid.uuid4().hex[:8]}", "财经号")
    arts = []
    for i in range(n):
        a = WechatArticle(
            account_id=acc.id, external_id=f"a{uuid.uuid4().hex[:8]}", title=f"文章{i}",
            digest="", cover_url=None, url=f"https://mp.weixin.qq.com/s/{uuid.uuid4().hex[:6]}",
            content=content, published_at=dt.datetime(2026, 7, i + 1, tzinfo=dt.UTC),
        )
        db.add(a)
        arts.append(a)
    await db.commit()
    return acc, arts


@pytest.mark.asyncio
async def test_ingest_source_document_resolves_and_readies(db_session, fast_limiter):
    from app.kb.backfill import ingest_source_document
    from app.kb.service import add_source_item

    kb = await _kb(db_session)
    _, arts = await _account_with_articles(db_session, 1, content="茅台" * 500)
    _, doc_id = await add_source_item(db_session, kb.id, "wechat_article", str(arts[0].id))
    await ingest_source_document(doc_id, "wechat_article", str(arts[0].id))

    doc = await db_session.get(KbDocument, doc_id)
    await db_session.refresh(doc)
    assert doc.status == "ready" and doc.chunk_count >= 1 and doc.text


@pytest.mark.asyncio
async def test_ingest_source_document_marks_failed_on_fetch_error(db_session, fast_limiter,
                                                                  monkeypatch):
    """抓取失败 → 该篇标 failed，错误可见，不影响别的文档。"""
    from app.kb.backfill import ingest_source_document
    from app.kb.service import add_source_item

    kb = await _kb(db_session)
    _, arts = await _account_with_articles(db_session, 1, content=None)
    _, doc_id = await add_source_item(db_session, kb.id, "wechat_article", str(arts[0].id))
    # content 为空且 backfill 内部建的 http client 会真发请求 → mock 掉使其失败
    from app.kb import backfill

    def _boom():
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="rate limited")))

    monkeypatch.setattr(backfill, "new_mp_client", _boom)
    await ingest_source_document(doc_id, "wechat_article", str(arts[0].id))

    doc = await db_session.get(KbDocument, doc_id)
    await db_session.refresh(doc)
    assert doc.status == "failed" and doc.error


@pytest.mark.asyncio
async def test_backfill_source_ingests_existing_articles(db_session, fast_limiter):
    from app.kb.backfill import backfill_source

    kb = await _kb(db_session)
    acc, arts = await _account_with_articles(db_session, 3)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="财经号")
    db_session.add(src)
    await db_session.commit()

    added = await backfill_source(src.id)
    assert added == 3
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument)
        .where(KbDocument.kb_id == kb.id, KbDocument.status == "ready")
    )).scalar_one()
    assert n == 3
    await db_session.refresh(src)
    assert src.status == "ready" and src.last_synced_at is not None


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db_session, fast_limiter):
    """重跑安全：进程重启丢了任务，下次同步补上，不产生重复。"""
    from app.kb.backfill import backfill_source

    kb = await _kb(db_session)
    acc, _ = await _account_with_articles(db_session, 2)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="号")
    db_session.add(src)
    await db_session.commit()

    assert await backfill_source(src.id) == 2
    assert await backfill_source(src.id) == 0        # 第二次全是 duplicate
    n = (await db_session.execute(
        select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
    )).scalar_one()
    assert n == 2


@pytest.mark.asyncio
async def test_backfill_aborts_after_consecutive_failures(db_session, fast_limiter, monkeypatch):
    """连续失败 3 篇即中止本批，别把几十篇全标脏。"""
    monkeypatch.setenv("KB_BACKFILL_MAX_FAILURES", "3")
    config.get_settings.cache_clear()

    from app.kb import backfill

    kb = await _kb(db_session)
    acc, _ = await _account_with_articles(db_session, 10, content=None)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="号")
    db_session.add(src)
    await db_session.commit()

    calls = []

    async def _always_fail(db, source_type, source_ref_id, http=None):
        calls.append(source_ref_id)
        raise RuntimeError("被限流")

    monkeypatch.setattr(backfill, "resolve_text", _always_fail)
    added = await backfill.backfill_source(src.id)
    assert added == 0
    assert len(calls) == 3            # 第 3 次连续失败后中止，不再碰剩下 7 篇
    await db_session.refresh(src)
    assert src.status == "failed" and src.error


@pytest.mark.asyncio
async def test_backfill_marks_limited_on_quota(db_session, fast_limiter, monkeypatch):
    """触顶时置 status=limited 停止入库，面板可见，不静默丢弃。"""
    monkeypatch.setenv("KB_MAX_DOCUMENTS_PER_KB", "1")
    config.get_settings.cache_clear()

    from app.kb.backfill import backfill_source

    kb = await _kb(db_session)
    acc, _ = await _account_with_articles(db_session, 3)
    src = KbSource(kb_id=kb.id, source_type="wechat_account",
                   source_ref_id=str(acc.id), display_name="号")
    db_session.add(src)
    await db_session.commit()

    added = await backfill_source(src.id)
    assert added == 1                 # 第 2 篇时触顶
    await db_session.refresh(src)
    assert src.status == "limited"


@pytest.mark.asyncio
async def test_poll_hook_ingests_new_articles(db_session, fast_limiter):
    """增量：poll 到新文章后，订阅了该号的每个 KbSource 各入一份。"""
    from app.kb.backfill import ingest_new_articles_for_account

    kb1 = await _kb(db_session)
    kb2 = await _kb(db_session)
    acc, arts = await _account_with_articles(db_session, 2)
    for kb in (kb1, kb2):
        db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                                source_ref_id=str(acc.id), display_name="号"))
    await db_session.commit()

    added = await ingest_new_articles_for_account(acc.id, [a.id for a in arts])
    assert added == 4                 # 2 篇 × 2 个库
    for kb in (kb1, kb2):
        n = (await db_session.execute(
            select(func.count()).select_from(KbDocument).where(KbDocument.kb_id == kb.id)
        )).scalar_one()
        assert n == 2


@pytest.mark.asyncio
async def test_poll_hook_skips_disabled_sources(db_session, fast_limiter):
    from app.kb.backfill import ingest_new_articles_for_account

    kb = await _kb(db_session)
    acc, arts = await _account_with_articles(db_session, 1)
    db_session.add(KbSource(kb_id=kb.id, source_type="wechat_account",
                            source_ref_id=str(acc.id), display_name="号", enabled=False))
    await db_session.commit()
    assert await ingest_new_articles_for_account(acc.id, [arts[0].id]) == 0


@pytest.mark.asyncio
async def test_poll_hook_noop_without_subscribers(db_session, fast_limiter):
    from app.kb.backfill import ingest_new_articles_for_account

    acc, arts = await _account_with_articles(db_session, 1)
    assert await ingest_new_articles_for_account(acc.id, [arts[0].id]) == 0

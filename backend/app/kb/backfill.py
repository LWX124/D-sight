"""后台入库任务：单篇 resolve+切片，整号回填，poll 增量钩子。

三者都自己开 session（跑在 BackgroundTasks / scheduler 里，没有请求 session），
且都幂等——重跑只会得到 duplicate，不产生重复文档。
"""
import logging
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.kb.ingest import ingest_text
from app.kb.models import Kb, KbDocument, KbSource
from app.kb.service import QuotaExceeded, add_source_item, check_document_quota
from app.kb.sources import resolve_text
from app.social.wechat.client import new_mp_client

_log = logging.getLogger(__name__)
# 需要走网络抓正文的来源。news_item 直接读库，不必占限流 slot。
_NEEDS_FETCH = {"wechat_article"}


async def _resolve(source_type: str, source_ref_id: str) -> str:
    """取正文。需要回源的来源由 fetch_article_content 内部走限流 slot（与前台懒抓
    共用同一个 slot），这里不再重复占——asyncio.Lock 不可重入，重复 acquire 会死锁。
    """
    sm = get_sessionmaker()
    if source_type not in _NEEDS_FETCH:
        async with sm() as db:
            return await resolve_text(db, source_type, source_ref_id)
    async with new_mp_client() as http, sm() as db:
        return await resolve_text(db, source_type, source_ref_id, http=http)


async def _mark_doc_failed(document_id: uuid.UUID, message: str) -> None:
    sm = get_sessionmaker()
    async with sm() as db:
        doc = await db.get(KbDocument, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error = message[:500]
            await db.commit()


async def ingest_source_document(
    document_id: uuid.UUID, source_type: str, source_ref_id: str
) -> None:
    """单篇后台任务：取正文 → 切片入库。失败落在 doc.status='failed'，绝不抛。

    跑在 BackgroundTasks 里——没有调用方接得住异常，故失败只写库。
    backfill_source / ingest_new_articles 走 _ingest_one，那条路径会向上抛，
    以便连续失败计数与配额中止策略生效。
    """
    try:
        text = await _resolve(source_type, source_ref_id)
    except Exception as e:  # noqa: BLE001 — 后台任务：失败写库不抛
        _log.exception("resolve failed for document %s", document_id)
        await _mark_doc_failed(document_id, f"正文获取失败：{e}")
        return
    await ingest_text(document_id, text)


async def _owner_of(db, kb_id: uuid.UUID):
    from app.auth.models import User

    return await db.scalar(select(User).join(Kb, Kb.owner_id == User.id).where(Kb.id == kb_id))


async def _ingest_one(kb_id: uuid.UUID, source_type: str, source_ref_id: str,
                      kb_source_id: uuid.UUID | None) -> str:
    """建行 + 入库，返回 'added' / 'duplicate'。

    配额异常与正文解析失败均向上抛，由调用方决定中止策略：
      - QuotaExceeded → backfill_source 置 limited 停止；poll 置 limited 跳过该源
      - 其它 Exception → backfill_source 计入连续失败；poll 记日志继续下一篇
    取正文失败时先把该篇标 failed 再抛，免得留一堆 pending 脏行。
    """
    sm = get_sessionmaker()
    async with sm() as db:
        owner = await _owner_of(db, kb_id)
        if owner is None:
            return "duplicate"        # 库已被删，静默跳过
        await check_document_quota(db, kb_id, owner)
        result, doc_id = await add_source_item(db, kb_id, source_type, source_ref_id,
                                              kb_source_id=kb_source_id)
    if result == "duplicate":
        return "duplicate"
    try:
        text = await _resolve(source_type, source_ref_id)
    except Exception as e:  # noqa: BLE001 — 标 failed 后向上抛，让调用方计数/中止
        _log.warning("resolve failed for document %s: %s", doc_id, e)
        await _mark_doc_failed(doc_id, f"正文获取失败：{e}")
        raise
    await ingest_text(doc_id, text)
    return "added"


async def backfill_source(kb_source_id: uuid.UUID) -> int:
    """把该号在 wechat_articles 里已有的文章逐篇入库。不回溯翻页拉历史。

    重跑安全（查重幂等）。连续失败达 kb_backfill_max_failures 篇即中止本批——
    正文抓取一旦被风控挡住，继续跑只会把几十篇全标脏。
    """
    s = get_settings()
    sm = get_sessionmaker()
    async with sm() as db:
        src = await db.get(KbSource, kb_source_id)
        if src is None or not src.enabled:
            return 0
        src.status = "syncing"
        src.error = None
        await db.commit()
        kb_id, ref, source_type = src.kb_id, src.source_ref_id, src.source_type

    article_ids = await _pending_article_ids(source_type, ref, s.kb_backfill_batch_limit)

    added, consecutive_failures, final_status, err = 0, 0, "ready", None
    for aid in article_ids:
        try:
            if await _ingest_one(kb_id, "wechat_article", str(aid), kb_source_id) == "added":
                added += 1
            consecutive_failures = 0
        except QuotaExceeded as e:
            final_status, err = "limited", e.message
            break
        except Exception as e:  # noqa: BLE001 — 单篇失败隔离
            _log.warning("backfill failed for article %s: %s", aid, e)
            consecutive_failures += 1
            if consecutive_failures >= s.kb_backfill_max_failures:
                final_status = "failed"
                err = f"连续 {consecutive_failures} 篇获取失败，已中止本次同步：{e}"
                break

    import datetime as dt

    async with sm() as db:
        src = await db.get(KbSource, kb_source_id)
        if src is not None:
            src.status = final_status
            src.error = (err or None) and err[:500]
            src.last_synced_at = dt.datetime.now(dt.UTC)
            await db.commit()
    return added


async def _pending_article_ids(source_type: str, source_ref_id: str, limit: int) -> list[uuid.UUID]:
    """该号已有文章里、尚未入过库的，按发布时间倒序取前 limit 篇。"""
    if source_type != "wechat_account":
        return []
    from app.social.models import WechatArticle

    sm = get_sessionmaker()
    async with sm() as db:
        rows = (await db.execute(
            select(WechatArticle.id)
            .where(WechatArticle.account_id == uuid.UUID(source_ref_id))
            .order_by(WechatArticle.published_at.desc()).limit(limit)
        )).scalars().all()
    return list(rows)


async def ingest_new_articles_for_account(
    account_id: uuid.UUID, article_ids: list[uuid.UUID]
) -> int:
    """poll 钩子：本轮该号新增的文章，为订阅了它的每个 KbSource 各入一份。"""
    if not article_ids:
        return 0
    sm = get_sessionmaker()
    async with sm() as db:
        sources = (await db.execute(
            select(KbSource).where(
                KbSource.source_type == "wechat_account",
                KbSource.source_ref_id == str(account_id),
                KbSource.enabled.is_(True),
            )
        )).scalars().all()
        targets = [(src.kb_id, src.id) for src in sources]
    if not targets:
        return 0

    added = 0
    for kb_id, src_id in targets:
        for aid in article_ids:
            try:
                if await _ingest_one(kb_id, "wechat_article", str(aid), src_id) == "added":
                    added += 1
            except QuotaExceeded as e:
                async with sm() as db:
                    src = await db.get(KbSource, src_id)
                    if src is not None:
                        src.status = "limited"
                        src.error = e.message[:500]
                        await db.commit()
                break
            except Exception:  # noqa: BLE001 — 单篇失败隔离，不拖累同批
                _log.exception("kb poll ingest failed: kb=%s article=%s", kb_id, aid)
    return added

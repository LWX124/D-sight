"""Phase 4: 正文获取与缓存。

内容正文（body_text）获取策略：
1. 优先从 DB 读取（缓存）
2. 过期或缺失时从 Provider 获取
3. 获取后写入 DB 并设置过期时间

缓存策略：正文与字幕统一保留 90 天；收藏内容不设置过期时间。
媒体只保留上游 URL/元数据，本模块不下载图片、音频或视频文件。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.providers.base import ItemDTO, SocialProvider
from app.social.provider_audit import (
    audited_provider_call,
    provider_audit_name,
    redact_secret_text,
)
from app.social.providers.redfox import RedFoxProvider, is_allowed_wechat_article_url
from app.social.retention import CONTENT_BODY_RETENTION
from app.social.unified import compute_content_hash
from app.social.unified_models import ContentBookmark, SocialItem
from app.social.wechat.parser import html_to_text

logger = logging.getLogger(__name__)

BODY_CACHE_TTL = CONTENT_BODY_RETENTION


async def _is_bookmarked(db: AsyncSession, item: SocialItem) -> bool:
    bookmark_id = await db.scalar(
        select(ContentBookmark.id).where(ContentBookmark.item_id == item.id).limit(1)
    )
    return bookmark_id is not None


async def _persist_fetched_body(
    db: AsyncSession,
    item: SocialItem,
    *,
    body_text: str | None = None,
    transcript_text: str | None = None,
    fetched_at: datetime,
) -> None:
    """Persist only a successful text fetch and refresh its content fingerprint."""
    if body_text:
        item.body_text = body_text
    if transcript_text:
        item.transcript_text = transcript_text
    item.body_fetched_at = fetched_at
    item.body_expires_at = None if await _is_bookmarked(db, item) else fetched_at + BODY_CACHE_TTL
    item.content_hash = compute_content_hash(item.title, item.body_text, item.url)
    await db.flush()


async def get_body_text(
    db: AsyncSession,
    item: SocialItem,
    provider: SocialProvider | None = None,
    force_refresh: bool = False,
) -> str | None:
    """获取内容正文。

    优先从 DB 读取，过期时从 Provider 获取。
    """
    now = datetime.now(timezone.utc)

    # 检查缓存
    cached_text = (
        item.body_text if item.platform == "wechat" else (item.body_text or item.transcript_text)
    )
    if not force_refresh and cached_text and item.body_fetched_at:
        if await _is_bookmarked(db, item) or (
            item.body_expires_at is not None and item.body_expires_at > now
        ):
            if item.platform == "wechat":
                normalized_text = html_to_text(item.body_text or "")
                if normalized_text and normalized_text != item.body_text:
                    item.body_text = normalized_text
                    item.content_hash = compute_content_hash(item.title, item.body_text, item.url)
                    await db.flush()
            return item.body_text

    # RedFox's URL-based detail endpoint is a paid external call. Validate the
    # stored source URL before reaching the audited provider boundary.
    if item.platform == "wechat" and not is_allowed_wechat_article_url(item.url):
        return None

    # 需要从 Provider 获取
    if not provider:
        return None if item.platform == "wechat" else item.body_text

    try:
        dto = ItemDTO(
            platform=item.platform,
            external_id=item.external_id,
            content_type=item.content_type,
            url=item.url,
        )
        detail = await audited_provider_call(
            provider_client=provider,
            provider=provider_audit_name(provider),
            platform=item.platform,
            endpoint="item-detail",
            operation="fetch_item_detail",
            call=lambda: provider.fetch_item_detail(dto),
        )

        body_text = detail.body_text if detail.body_text and detail.body_text.strip() else None
        transcript_text = (
            detail.transcript_text
            if detail.transcript_text and detail.transcript_text.strip()
            else None
        )
        if body_text or transcript_text:
            await _persist_fetched_body(
                db,
                item,
                body_text=body_text,
                transcript_text=transcript_text,
                fetched_at=now,
            )
            return body_text

    except Exception as e:
        safe_error = redact_secret_text(e, (getattr(provider, "_api_key", ""),))
        logger.warning(
            "Failed to fetch body for %s/%s: %s",
            item.platform,
            item.external_id,
            safe_error,
        )

    # The WeChat contract deliberately hides expired text when refresh fails.
    # Other platforms may have list-complete bodies and no detail capability;
    # preserve their established detail response instead of blanking it.
    return None if item.platform == "wechat" else item.body_text


async def prefetch_bodies(
    db: AsyncSession,
    items: list[SocialItem],
    provider: RedFoxProvider,
    max_concurrent: int = 5,
) -> dict:
    """批量预取正文。返回统计信息。"""
    from asyncio import Semaphore

    sem = Semaphore(max_concurrent)
    stats = {"fetched": 0, "cached": 0, "failed": 0}

    async def _fetch_one(item: SocialItem):
        async with sem:
            result = await get_body_text(db, item, provider)
            if result and result != item.body_text:
                stats["fetched"] += 1
            elif result:
                stats["cached"] += 1
            else:
                stats["failed"] += 1

    # 只预取需要详情的平台（小红书）
    xhs_items = [i for i in items if i.platform == "xiaohongshu" and not i.body_text]
    for item in xhs_items:
        await _fetch_one(item)

    return stats


async def expire_cached_content(db: AsyncSession, now: datetime | None = None) -> int:
    """Remove expired text/transcripts unless any user bookmarked the item.

    Only text columns are cleared. Media is never downloaded by this subsystem,
    so URL metadata remains untouched.
    """
    cutoff = now or datetime.now(timezone.utc)
    bookmarked = exists(select(ContentBookmark.id).where(ContentBookmark.item_id == SocialItem.id))
    result = await db.execute(
        update(SocialItem)
        .where(
            SocialItem.body_expires_at.is_not(None),
            SocialItem.body_expires_at <= cutoff,
            ~bookmarked,
        )
        .values(
            body_text=None,
            transcript_text=None,
            body_fetched_at=None,
            body_expires_at=None,
        )
    )
    await db.flush()
    return result.rowcount

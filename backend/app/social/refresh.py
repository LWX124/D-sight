"""Real, publisher-global refresh orchestration for the unified feed."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.models import WechatAccount, WechatArticle, WeiboAccount, WeiboPost
from app.social.provider_audit import (
    audited_provider_call,
    provider_audit_name,
    redact_secret_text,
)
from app.social.providers import ItemDTO, MetricsDTO, PublisherDTO, get_provider
from app.social.providers.redfox import RedFoxProvider
from app.social.unified import record_metrics, upsert_item
from app.social.unified_models import SocialPublisher, SocialSubscription


def _publisher_dto(publisher: SocialPublisher) -> PublisherDTO:
    return PublisherDTO(
        platform=publisher.platform,
        external_id=publisher.external_id,
        name=publisher.name,
        avatar=publisher.avatar,
        description=publisher.description,
        profile_url=publisher.profile_url,
        provider=publisher.provider or "",
        provider_ref=publisher.provider_ref,
        platform_metadata=publisher.platform_metadata or {},
    )


def _has_metrics(metrics: MetricsDTO) -> bool:
    return any(
        value is not None
        for value in (
            metrics.view_count,
            metrics.like_count,
            metrics.comment_count,
            metrics.share_count,
            metrics.collect_count,
            metrics.provider_rank,
        )
    ) or bool(metrics.raw)


async def _persist_dtos(
    db: AsyncSession,
    publisher: SocialPublisher,
    items: list[ItemDTO],
) -> int:
    persisted = 0
    for dto in items:
        if not dto.external_id:
            continue
        item = await upsert_item(db, dto, publisher.id)
        if _has_metrics(dto.metrics):
            await record_metrics(db, item.id, dto.metrics)
        persisted += 1
    return persisted


async def _refresh_redfox(
    db: AsyncSession,
    publisher: SocialPublisher,
    settings: Any,
) -> int:
    provider = get_provider(publisher.platform, settings)
    if not isinstance(provider, RedFoxProvider):
        raise RuntimeError("publisher is not configured for RedFox")
    capabilities = provider.capabilities(publisher.platform)
    if not capabilities.get("account_item_list"):
        await provider.aclose()
        reason = capabilities.get("missing_reason") or "account item list unavailable"
        raise NotImplementedError(str(reason))
    try:
        items = await audited_provider_call(
            provider_client=provider,
            provider=provider_audit_name(provider),
            platform=publisher.platform,
            endpoint="publisher-items",
            operation="refresh_publisher",
            call=lambda: provider.fetch_publisher_items(_publisher_dto(publisher)),
        )
        return await _persist_dtos(db, publisher, items)
    finally:
        await provider.aclose()


async def _refresh_weibo(
    db: AsyncSession,
    publisher: SocialPublisher,
    settings: Any,
) -> int:
    from app.social.weibo.ingest import ingest_account

    account = await db.scalar(select(WeiboAccount).where(WeiboAccount.uid == publisher.external_id))
    if account is None:
        raise LookupError("微博发布者未绑定旧采集账号")
    await audited_provider_call(
        provider_client=None,
        provider="weibo",
        platform="weibo",
        endpoint="legacy-ingest",
        operation="refresh_publisher",
        call=lambda: ingest_account(db, account),
        estimated_cost=0,
    )
    return await project_weibo_posts(db, publisher, account, settings)


async def project_weibo_posts(
    db: AsyncSession,
    publisher: SocialPublisher,
    account: WeiboAccount,
    settings: Any,
) -> int:
    """Mirror already captured Weibo snapshots without another upstream call."""
    from app.social.providers.weibo import WeiboProvider

    posts = (
        await db.execute(
            select(WeiboPost)
            .where(WeiboPost.account_id == account.id)
            .order_by(desc(WeiboPost.published_at), desc(WeiboPost.id))
            .limit(settings.weibo_fetch_count * settings.weibo_max_pages)
        )
    ).scalars().all()
    return await _persist_dtos(
        db,
        publisher,
        [WeiboProvider.from_weibo_post(post) for post in posts],
    )


async def _refresh_wechat_mp(
    db: AsyncSession,
    publisher: SocialPublisher,
    settings: Any,
) -> int:
    from app.social.credentials import pick_credential
    from app.social.ingest import ingest_account
    from app.social.wechat.client import new_mp_client

    account = await db.scalar(
        select(WechatAccount).where(WechatAccount.fakeid == publisher.external_id)
    )
    if account is None:
        raise LookupError("公众号发布者未绑定旧采集账号")
    credential = await pick_credential(db)
    if credential is None:
        raise LookupError("公众号凭证池为空")
    async with new_mp_client() as http:
        await audited_provider_call(
            provider_client=None,
            provider="wechat_mp",
            platform="wechat",
            endpoint="legacy-ingest",
            operation="refresh_publisher",
            call=lambda: ingest_account(
                db,
                account,
                credential,
                http,
                count=settings.social_fetch_count,
            ),
            estimated_cost=0,
        )
    return await project_wechat_articles(db, publisher, account, settings)


async def project_wechat_articles(
    db: AsyncSession,
    publisher: SocialPublisher,
    account: WechatAccount,
    settings: Any,
) -> int:
    """Mirror captured WeChat articles into the unified content pool."""
    from app.social.providers.wechat_mp import WechatMpProvider

    articles = (
        await db.execute(
            select(WechatArticle)
            .where(WechatArticle.account_id == account.id)
            .order_by(desc(WechatArticle.published_at), desc(WechatArticle.id))
            .limit(settings.social_fetch_count)
        )
    ).scalars().all()
    return await _persist_dtos(
        db,
        publisher,
        [WechatMpProvider.from_wechat_article(article) for article in articles],
    )


async def refresh_publisher(
    db: AsyncSession,
    publisher: SocialPublisher,
    settings: Any,
) -> int:
    """Fetch once and write into the global content pool shared by all users."""
    if publisher.platform == "weibo":
        return await _refresh_weibo(db, publisher, settings)
    if publisher.platform == "wechat" and (
        publisher.provider == "wechat_mp" or not getattr(settings, "redfox_api_key", "")
    ):
        return await _refresh_wechat_mp(db, publisher, settings)
    return await _refresh_redfox(db, publisher, settings)


async def refresh_subscribed_publishers(
    db: AsyncSession,
    settings: Any,
    *,
    include_weibo: bool = True,
) -> dict[str, int]:
    """Refresh each globally subscribed publisher exactly once per scheduler round."""
    query = (
        select(SocialPublisher)
        .join(
            SocialSubscription,
            SocialSubscription.publisher_id == SocialPublisher.id,
        )
        .where(SocialSubscription.enabled.is_(True))
    )
    if not include_weibo:
        query = query.where(SocialPublisher.platform != "weibo")
    publishers = (
        await db.execute(query.distinct().order_by(SocialPublisher.id))
    ).scalars().all()
    stats = {
        "publishers": len(publishers),
        "succeeded": 0,
        "failed": 0,
        "skipped_locked": 0,
        "items": 0,
    }
    for publisher in publishers:
        try:
            acquired = await db.scalar(
                text(
                    "SELECT pg_try_advisory_xact_lock("
                    "hashtextextended(:publisher_id, 0))"
                ),
                {"publisher_id": str(publisher.id)},
            )
            if not acquired:
                await db.rollback()
                stats["skipped_locked"] += 1
                continue
            stats["items"] += await refresh_publisher(db, publisher, settings)
            publisher.last_synced_at = datetime.now(timezone.utc)
            publisher.last_sync_status = "ok"
            publisher.last_sync_error = None
            await db.commit()
            stats["succeeded"] += 1
        except Exception as exc:  # one provider/account must not abort the round
            await db.rollback()
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.last_sync_status = "error"
                failed_publisher.last_sync_error = redact_secret_text(
                    exc,
                    (getattr(settings, "redfox_api_key", ""),),
                )
                await db.commit()
            stats["failed"] += 1
    return stats


async def sync_legacy_weibo_publishers(
    db: AsyncSession,
    settings: Any,
) -> dict[str, int]:
    """Project the safe legacy Weibo polling results into the unified feed.

    Scheduled Weibo collection must continue to use ``weibo.job`` because it
    owns credential state, account gaps, rate-limit round stops, and account
    isolation. This function performs only the storage-to-storage projection,
    so the unified scheduler never issues a second upstream request.
    """
    rows = (
        await db.execute(
            select(SocialPublisher, WeiboAccount)
            .join(
                SocialSubscription,
                SocialSubscription.publisher_id == SocialPublisher.id,
            )
            .join(WeiboAccount, WeiboAccount.uid == SocialPublisher.external_id)
            .where(
                SocialSubscription.enabled.is_(True),
                SocialPublisher.platform == "weibo",
            )
            .distinct()
            .order_by(SocialPublisher.id)
        )
    ).all()
    stats = {"publishers": len(rows), "succeeded": 0, "failed": 0, "items": 0}
    for publisher, account in rows:
        try:
            async with db.begin_nested():
                stats["items"] += await project_weibo_posts(
                    db, publisher, account, settings
                )
                publisher.last_synced_at = account.last_synced_at
                publisher.last_sync_status = account.last_sync_status
                publisher.last_sync_error = account.last_sync_error
            stats["succeeded"] += 1
        except Exception as exc:
            publisher.last_sync_status = "error"
            publisher.last_sync_error = redact_secret_text(
                exc,
                (getattr(settings, "redfox_api_key", ""),),
            )
            stats["failed"] += 1
    await db.flush()
    return stats

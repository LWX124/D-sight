"""Real, publisher-global refresh orchestration for the unified feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import logging

import httpx
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.models import WechatAccount, WechatArticle, WeiboAccount, WeiboPost
from app.social.provider_audit import (
    audited_provider_call,
    provider_audit_name,
    redact_secret_text,
)
from app.social.budget import ProviderBudgetExceeded
from app.social.identity import ensure_publisher_identity, resolve_wechat_identity
from app.social.providers import (
    ItemDTO,
    MetricsDTO,
    ProviderCoverageGap,
    PublisherDTO,
    get_provider,
)
from app.social.providers.redfox import RedFoxProvider
from app.social.unified import record_metrics, upsert_item
from app.social.unified_models import (
    SocialPublisher,
    SocialPublisherIdentity,
    SocialSubscription,
)
from app.social.wechat.errors import (
    FreqControlError,
    SessionExpiredError,
    TransientMpError,
)

_REDFOX_REFRESH = timedelta(hours=4)
_REDFOX_REPROBE = timedelta(days=30)
logger = logging.getLogger(__name__)


class CredentialUnavailableError(LookupError):
    """No usable platform-managed credential is available."""


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
    identity: SocialPublisherIdentity | None = None,
) -> int:
    from app.social.credentials import pick_credential
    from app.social.ingest import ingest_account
    from app.social.wechat.client import new_mp_client

    fakeid = identity.external_id if identity is not None else publisher.external_id
    account = await db.scalar(select(WechatAccount).where(WechatAccount.fakeid == fakeid))
    if account is None:
        raise LookupError("公众号发布者未绑定旧采集账号")
    credential = await pick_credential(db, commit=False)
    if credential is None:
        raise CredentialUnavailableError("公众号凭证池为空")
    try:
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
                    commit=False,
                ),
                estimated_cost=0,
            )
    except SessionExpiredError as exc:
        exc.credential_id = credential.id
        raise
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
    """Refresh through durable identities; only an explicit gap may fall back."""
    if publisher.platform == "weibo":
        return await _refresh_weibo(db, publisher, settings)
    identities = (
        await db.execute(
            select(SocialPublisherIdentity).where(
                SocialPublisherIdentity.publisher_id == publisher.id
            )
        )
    ).scalars().all()
    if not identities:
        provider = publisher.provider or (
            "wechat_mp"
            if publisher.platform == "wechat" and not getattr(settings, "redfox_api_key", "")
            else "redfox"
        )
        identities = [
            await ensure_publisher_identity(
                db,
                publisher,
                provider=provider,
                external_id=publisher.external_id,
            )
        ]

    by_provider = {identity.provider: identity for identity in identities}
    if publisher.platform != "wechat":
        return await _refresh_redfox(db, publisher, settings)

    now = datetime.now(timezone.utc)
    redfox = by_provider.get("redfox")
    wechat = by_provider.get("wechat_mp")
    should_probe_redfox = redfox is not None and (
        redfox.status == "active"
        or redfox.last_checked_at is None
        or redfox.last_checked_at <= now - _REDFOX_REPROBE
    )
    if should_probe_redfox:
        redfox.last_attempt_at = now
        redfox.last_checked_at = now
        try:
            count = await _refresh_redfox(db, publisher, settings)
        except ProviderCoverageGap as exc:
            logger.info(
                "social coverage gap publisher_id=%s provider=redfox code=%s",
                publisher.id,
                exc.code,
            )
            redfox.status = "coverage_gap"
            redfox.last_error_code = exc.code
            redfox.last_error_message = str(exc)
            redfox.next_due_at = now + _REDFOX_REPROBE
            publisher.last_sync_error_code = exc.code
            publisher.last_sync_error = str(exc)
        except (httpx.HTTPError, RuntimeError) as exc:
            # A transient/configuration failure must never create a new
            # fallback binding. Once a typed coverage gap has already bound an
            # active WeChat identity, however, a low-frequency RedFox reprobe
            # must not block that established fallback path.
            if wechat is None or wechat.status != "active":
                raise
            logger.warning(
                "social redfox reprobe failed; keeping established fallback "
                "publisher_id=%s error_type=%s",
                publisher.id,
                type(exc).__name__,
            )
            redfox.last_error_code = "redfox_upstream_error"
            redfox.last_error_message = redact_secret_text(
                exc,
                (getattr(settings, "redfox_api_key", ""),),
            )
            redfox.next_due_at = now + _REDFOX_REPROBE
        else:
            redfox.status = "active"
            redfox.last_success_at = now
            redfox.next_due_at = now + _REDFOX_REFRESH
            redfox.last_error_code = None
            redfox.last_error_message = None
            publisher.sync_provider = "redfox"
            if wechat is not None:
                wechat.status = "disabled"
                wechat.next_due_at = None
            return count

    if redfox is None and wechat is None:
        raise LookupError("公众号发布者没有可用 provider identity")
    if not getattr(settings, "social_wechat_fallback_enabled", False):
        publisher.sync_state = "upstream_error"
        publisher.sync_provider = "redfox"
        publisher.next_sync_at = now + _REDFOX_REPROBE
        return 0

    if not await _claim_fallback_capacity(
        db,
        publisher,
        settings,
        redfox,
        fallback_identity=wechat,
    ):
        return 0
    if wechat is None:
        from app.social.credentials import pick_credential
        from app.social.wechat.client import new_mp_client, search_biz

        credential = await pick_credential(db, commit=False)
        if credential is None:
            publisher.sync_state = "credential_unavailable"
            publisher.sync_provider = "wechat_mp"
            publisher.last_sync_error_code = "credential_unavailable"
            publisher.last_sync_error = "平台公众号凭证暂不可用"
            publisher.next_sync_at = now + timedelta(hours=24)
            return 0
        publisher.sync_state = "resolving_identity"
        try:
            async with new_mp_client() as http:
                candidates = await search_biz(http, credential, publisher.name)
        except SessionExpiredError as exc:
            exc.credential_id = credential.id
            raise
        _, wechat = await resolve_wechat_identity(db, publisher, candidates)
        if wechat is None:
            publisher.next_sync_at = now + _REDFOX_REPROBE
            return 0

    count = await _refresh_wechat_mp(db, publisher, settings, wechat)
    interval_hours = 24 + (publisher.id.int % 49)
    wechat.status = "active"
    wechat.last_attempt_at = now
    wechat.last_success_at = now
    wechat.last_error_code = None
    wechat.last_error_message = None
    wechat.next_due_at = now + timedelta(hours=interval_hours)
    publisher.sync_provider = "wechat_mp"
    publisher.next_sync_at = wechat.next_due_at
    return count


async def _claim_fallback_capacity(
    db: AsyncSession,
    publisher: SocialPublisher,
    settings: Any,
    redfox_identity: SocialPublisherIdentity | None,
    *,
    fallback_identity: SocialPublisherIdentity | None = None,
) -> bool:
    """Serialize capacity admission and preserve FIFO waiting timestamps."""

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": 2_026_081_401}
    )
    other_active_count = await db.scalar(
        select(func.count(func.distinct(SocialPublisherIdentity.publisher_id)))
        .join(
            SocialSubscription,
            SocialSubscription.publisher_id == SocialPublisherIdentity.publisher_id,
        )
        .where(
            SocialPublisherIdentity.provider == "wechat_mp",
            SocialPublisherIdentity.status == "active",
            SocialPublisherIdentity.publisher_id != publisher.id,
            SocialSubscription.enabled.is_(True),
        )
    )
    if int(other_active_count or 0) < int(settings.social_wechat_fallback_capacity):
        if redfox_identity is not None:
            redfox_identity.status = "coverage_gap"
        if fallback_identity is not None:
            fallback_identity.status = "active"
            fallback_identity.waiting_since_at = None
        return True
    now = datetime.now(timezone.utc)
    publisher.sync_state = "waiting_capacity"
    publisher.sync_provider = "wechat_mp"
    publisher.last_sync_error_code = "waiting_capacity"
    publisher.last_sync_error = "公众号补缺容量已满，已按排队时间等待"
    publisher.next_sync_at = now + timedelta(hours=24)
    waiting_identity = fallback_identity or redfox_identity
    if waiting_identity is not None:
        waiting_identity.status = "waiting_capacity"
        waiting_identity.waiting_since_at = waiting_identity.waiting_since_at or now
        waiting_identity.next_due_at = publisher.next_sync_at
    if fallback_identity is not None and redfox_identity is not None:
        redfox_identity.status = "coverage_gap"
    logger.info(
        "social fallback waiting publisher_id=%s active=%d capacity=%d",
        publisher.id,
        int(other_active_count or 0),
        int(settings.social_wechat_fallback_capacity),
    )
    return False


async def enqueue_publisher_refresh(
    db: AsyncSession, publisher: SocialPublisher
) -> dict[str, Any]:
    """Coalesce repeated manual clicks into one durable publisher request."""

    now = datetime.now(timezone.utc)
    identities = (
        await db.execute(
            select(SocialPublisherIdentity).where(
                SocialPublisherIdentity.publisher_id == publisher.id
            )
        )
    ).scalars().all()
    if not identities:
        identity = await ensure_publisher_identity(
            db,
            publisher,
            provider=publisher.provider or "redfox",
            external_id=publisher.external_id,
        )
        identities = [identity]
    newly_requested = False
    for identity in identities:
        if identity.requested_at is None:
            identity.requested_at = now
            newly_requested = True
            if identity.next_due_at is None or identity.next_due_at > now:
                identity.next_due_at = now
    if newly_requested and (
        publisher.next_sync_at is None or publisher.next_sync_at > now
    ):
        publisher.next_sync_at = now
    if publisher.sync_state not in {"waiting_capacity", "rate_limited"}:
        publisher.sync_state = "queued"
    await db.commit()
    logger.info(
        "social refresh queued publisher_id=%s state=%s next_sync_at=%s",
        publisher.id,
        publisher.sync_state,
        publisher.next_sync_at,
    )
    return {
        "state": publisher.sync_state,
        "publisher_id": str(publisher.id),
        "next_sync_at": publisher.next_sync_at,
    }


async def refresh_subscribed_publishers(
    db: AsyncSession,
    settings: Any,
    *,
    include_weibo: bool = True,
) -> dict[str, int]:
    """Dispatch due publisher jobs once globally, ordered by durable due time."""
    now = datetime.now(timezone.utc)
    query = (
        select(SocialPublisher)
        .join(
            SocialSubscription,
            SocialSubscription.publisher_id == SocialPublisher.id,
        )
        .where(SocialSubscription.enabled.is_(True))
        .where(
            or_(
                SocialPublisher.next_sync_at.is_(None),
                SocialPublisher.next_sync_at <= now,
            )
        )
    )
    if not include_weibo:
        query = query.where(SocialPublisher.platform != "weibo")
    publishers = (
        await db.execute(
            query.distinct().order_by(
                SocialPublisher.next_sync_at.asc().nullsfirst(),
                SocialPublisher.id,
            )
        )
    ).scalars().all()
    stats = {
        "publishers": len(publishers),
        "succeeded": 0,
        "failed": 0,
        "skipped_locked": 0,
        "skipped_not_due": 0,
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
            # The candidate list was loaded before the advisory lock. Another
            # instance may have completed this publisher while we were waiting
            # to reach it, so refresh the durable due state after acquiring the
            # lock before issuing any upstream request.
            await db.refresh(publisher, attribute_names=["next_sync_at"])
            if publisher.next_sync_at is not None and publisher.next_sync_at > now:
                await db.rollback()
                stats["skipped_not_due"] += 1
                continue
            stats["items"] += await refresh_publisher(db, publisher, settings)
            publisher.sync_state = "ok" if publisher.sync_state not in {
                "waiting_capacity",
                "identity_unresolved",
                "identity_ambiguous",
                "credential_unavailable",
                "upstream_error",
            } else publisher.sync_state
            if publisher.sync_state == "ok":
                publisher.last_synced_at = datetime.now(timezone.utc)
                publisher.last_sync_status = "ok"
                publisher.last_sync_error = None
                publisher.last_sync_error_code = None
            if publisher.next_sync_at is None or publisher.next_sync_at <= now:
                publisher.next_sync_at = now + _REDFOX_REFRESH
            if publisher.sync_state == "ok":
                await db.execute(
                    text(
                        "UPDATE social_publisher_identities SET requested_at = NULL "
                        "WHERE publisher_id = :publisher_id"
                    ),
                    {"publisher_id": publisher.id},
                )
            await db.commit()
            stats["succeeded"] += 1
        except ProviderBudgetExceeded as exc:
            await db.rollback()
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.sync_state = "queued"
                failed_publisher.sync_provider = "wechat_mp"
                failed_publisher.last_sync_error_code = exc.code
                failed_publisher.last_sync_error = "今日公众号补缺预算已用完"
                failed_publisher.next_sync_at = exc.retry_at
                await db.commit()
            stats["failed"] += 1
        except CredentialUnavailableError:
            await db.rollback()
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.sync_state = "credential_unavailable"
                failed_publisher.sync_provider = "wechat_mp"
                failed_publisher.last_sync_error_code = "credential_unavailable"
                failed_publisher.last_sync_error = "平台公众号凭证暂不可用"
                failed_publisher.next_sync_at = now + timedelta(hours=24)
                await db.commit()
            stats["failed"] += 1
        except FreqControlError as exc:
            await db.rollback()
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.sync_state = "rate_limited"
                failed_publisher.sync_provider = "wechat_mp"
                failed_publisher.last_sync_error_code = "wechat_rate_limited"
                failed_publisher.last_sync_error = "微信风控冷却中，保留最近快照"
                failed_publisher.next_sync_at = now + timedelta(
                    seconds=max(1, exc.retry_after)
                )
                await db.commit()
            stats["failed"] += 1
        except SessionExpiredError as exc:
            await db.rollback()
            credential_id = getattr(exc, "credential_id", None)
            if credential_id is not None:
                from app.social.credentials import mark_expired

                await mark_expired(db, credential_id, commit=False)
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.sync_state = "credential_unavailable"
                failed_publisher.sync_provider = "wechat_mp"
                failed_publisher.last_sync_error_code = "credential_expired"
                failed_publisher.last_sync_error = "平台公众号凭证已失效"
                failed_publisher.next_sync_at = now + timedelta(hours=24)
                await db.commit()
            stats["failed"] += 1
        except TransientMpError as exc:
            await db.rollback()
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.sync_state = "upstream_error"
                failed_publisher.sync_provider = "wechat_mp"
                failed_publisher.last_sync_error_code = "wechat_upstream_error"
                failed_publisher.last_sync_error = redact_secret_text(exc, ())
                failed_publisher.next_sync_at = now + timedelta(hours=24)
                await db.commit()
            stats["failed"] += 1
        except Exception as exc:  # one provider/account must not abort the round
            await db.rollback()
            failed_publisher = await db.get(SocialPublisher, publisher.id)
            if failed_publisher is not None:
                failed_publisher.last_sync_status = "error"
                failed_publisher.sync_state = "upstream_error"
                failed_publisher.last_sync_error_code = "upstream_error"
                failed_publisher.last_sync_error = redact_secret_text(
                    exc,
                    (getattr(settings, "redfox_api_key", ""),),
                )
                failed_publisher.next_sync_at = now + _REDFOX_REFRESH
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

"""Unified subscription feed, discovery, detail, and refresh APIs."""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.social.body_fetch import get_body_text
from app.social.provider_audit import audited_provider_call, provider_audit_name
from app.social.providers import PublisherDTO, get_provider
from app.social.providers.redfox import RedFoxProvider
from app.social.refresh import refresh_publisher
from app.social.schemas import (
    FeedItemDetailOut,
    FeedItemOut,
    FeedPageOut,
    PublisherSearchOut,
    UnifiedSubscribeIn,
    UnifiedSubscriptionOut,
)
from app.social.subscription_sync import (
    delete_unified_subscription_pair,
    ensure_subscription_for_publisher,
)
from app.social.unified import (
    decode_feed_cursor,
    get_feed,
    get_item_for_user,
    get_publisher_by_external,
    serialize_feed_item,
    upsert_publisher,
)
from app.social.unified_models import SocialPublisher, SocialSubscription

router = APIRouter(tags=["social-feed"])
_REFRESH_COOLDOWN_SECONDS = 15 * 60
logger = logging.getLogger(__name__)


async def _release_refresh_cooldown(redis, key: str) -> None:
    try:
        await redis.delete(key)
    except Exception as exc:
        logger.warning("social refresh cooldown release failed: %s", exc)


@router.get("/feed", response_model=FeedPageOut)
async def feed(
    publisher_id: uuid.UUID | None = None,
    before: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedPageOut:
    try:
        cursor = decode_feed_cursor(before) if before else None
    except ValueError as exc:
        raise HTTPException(400, "before 游标无效") from exc
    page = await get_feed(db, user.id, publisher_id, cursor, limit)
    return FeedPageOut(
        items=[FeedItemOut(**item) for item in page["items"]],
        next_before=page["next_before"],
    )


async def _refresh_for_user(
    publisher_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> dict:
    subscription = await db.scalar(
        select(SocialSubscription).where(
            SocialSubscription.user_id == user.id,
            SocialSubscription.publisher_id == publisher_id,
            SocialSubscription.enabled.is_(True),
        )
    )
    if subscription is None:
        raise HTTPException(403, "只能刷新自己已启用的订阅")
    publisher = await db.get(SocialPublisher, publisher_id)
    if publisher is None:
        raise HTTPException(404, "发布者不存在")

    acquired_db = await db.scalar(
        text(
            "SELECT pg_try_advisory_xact_lock("
            "hashtextextended(:publisher_id, 0))"
        ),
        {"publisher_id": str(publisher_id)},
    )
    if not acquired_db:
        raise HTTPException(409, "该发布者正在刷新，请稍后再试")

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    cooldown_key = f"social:refresh:publisher:{publisher_id}"
    try:
        try:
            acquired = await redis.set(
                cooldown_key,
                "1",
                ex=_REFRESH_COOLDOWN_SECONDS,
                nx=True,
            )
        except Exception as exc:  # DB advisory lock remains the correctness boundary
            logger.warning("social refresh cooldown unavailable; fail-open: %s", exc)
            acquired = True
        if not acquired:
            ttl = max(1, await redis.ttl(cooldown_key))
            raise HTTPException(
                429,
                f"该发布者刚刷新过，请 {ttl} 秒后再试",
                headers={"Retry-After": str(ttl)},
            )
        try:
            fetched = await refresh_publisher(db, publisher, settings)
            publisher.last_synced_at = datetime.now(timezone.utc)
            publisher.last_sync_status = "ok"
            publisher.last_sync_error = None
            await db.commit()
        except NotImplementedError as exc:
            await db.rollback()
            await _release_refresh_cooldown(redis, cooldown_key)
            raise HTTPException(422, str(exc)) from exc
        except LookupError as exc:
            await db.rollback()
            await _release_refresh_cooldown(redis, cooldown_key)
            raise HTTPException(409, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            await db.rollback()
            await _release_refresh_cooldown(redis, cooldown_key)
            raise HTTPException(503, "发布者刷新失败，请稍后重试") from exc
    finally:
        await redis.aclose()
    return {"ok": True, "publisher_id": str(publisher_id), "fetched": fetched}


@router.post("/publishers/{publisher_id}/refresh")
async def refresh_publisher_route(
    publisher_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _refresh_for_user(publisher_id, user, db)


@router.post("/feed/refresh", include_in_schema=False)
async def refresh_feed_compat(
    publisher_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _refresh_for_user(publisher_id, user, db)


@router.get("/subscriptions", response_model=list[UnifiedSubscriptionOut])
async def list_unified_subscriptions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UnifiedSubscriptionOut]:
    rows = (
        await db.execute(
            select(SocialSubscription, SocialPublisher)
            .join(SocialPublisher, SocialSubscription.publisher_id == SocialPublisher.id)
            .where(SocialSubscription.user_id == user.id)
            .order_by(desc(SocialSubscription.created_at))
        )
    ).all()
    return [
        UnifiedSubscriptionOut(
            id=str(subscription.id),
            publisher_id=str(publisher.id),
            platform=publisher.platform,
            external_id=publisher.external_id,
            name=publisher.name,
            avatar=publisher.avatar,
            enabled=subscription.enabled,
        )
        for subscription, publisher in rows
    ]


@router.post("/subscriptions", response_model=UnifiedSubscriptionOut)
async def add_unified_subscription(
    body: UnifiedSubscribeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnifiedSubscriptionOut:
    publisher = await db.get(SocialPublisher, body.publisher_id) if body.publisher_id else None
    if body.publisher_id and publisher is None:
        raise HTTPException(404, "发布者不存在")
    if publisher is not None:
        supplied = {
            "platform": body.platform,
            "external_id": body.external_id,
            "name": body.name,
        }
        for field, value in supplied.items():
            if value is not None and value != getattr(publisher, field):
                raise HTTPException(422, f"{field} 与 publisher_id 不匹配")
    else:
        assert body.platform and body.external_id and body.name
        publisher = await get_publisher_by_external(db, body.platform, body.external_id)
        if publisher is None:
            publisher = await upsert_publisher(
                db,
                PublisherDTO(
                    platform=body.platform,
                    external_id=body.external_id,
                    name=body.name,
                    avatar=body.avatar,
                ),
            )

    try:
        provider = get_provider(publisher.platform, get_settings())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    capabilities = provider.capabilities(publisher.platform)
    if isinstance(provider, RedFoxProvider):
        await provider.aclose()
    if not capabilities.get("account_item_list"):
        reason = capabilities.get("missing_reason") or "该平台不支持账号作品列表"
        raise HTTPException(422, str(reason))

    subscription = await ensure_subscription_for_publisher(db, user.id, publisher)
    await db.commit()
    return UnifiedSubscriptionOut(
        id=str(subscription.id),
        publisher_id=str(publisher.id),
        platform=publisher.platform,
        external_id=publisher.external_id,
        name=publisher.name,
        avatar=publisher.avatar,
        enabled=subscription.enabled,
    )


@router.delete("/subscriptions/{sub_id}")
async def remove_unified_subscription(
    sub_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    subscription = await db.get(SocialSubscription, sub_id)
    if subscription is None or subscription.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    await delete_unified_subscription_pair(
        db,
        user_id=user.id,
        subscription=subscription,
    )
    await db.commit()
    return {"ok": True}


@router.get("/publishers/search", response_model=list[PublisherSearchOut])
async def search_publishers(
    platform: str = Query(..., pattern="^(wechat|weibo|xiaohongshu|bilibili)$"),
    q: str = Query(..., min_length=1, max_length=100),
    user: User = Depends(get_current_user),
) -> list[PublisherSearchOut]:
    del user
    try:
        provider = get_provider(platform, get_settings())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    capabilities = provider.capabilities(platform)
    if not capabilities.get("publisher_search"):
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
        raise HTTPException(422, capabilities.get("missing_reason") or "该平台不支持账号搜索")
    try:
        publishers = await audited_provider_call(
            provider_client=provider,
            provider=provider_audit_name(provider),
            platform=platform,
            endpoint="publisher-search",
            operation="search_publishers",
            call=lambda: provider.search_publishers(platform, q.strip()),
        )
    except Exception as exc:
        raise HTTPException(503, "发布者搜索失败，请稍后重试") from exc
    finally:
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
    return [
        PublisherSearchOut(
            platform=publisher.platform,
            external_id=publisher.external_id,
            name=publisher.name,
            avatar=publisher.avatar,
            description=publisher.description,
            provider=publisher.provider,
        )
        for publisher in publishers
        if publisher.external_id and publisher.name
    ]


@router.get("/items/{item_id}", response_model=FeedItemDetailOut)
async def get_item_detail(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedItemDetailOut:
    row = await get_item_for_user(db, user.id, item_id)
    if row is None:
        raise HTTPException(404, "内容不存在")
    item, publisher = row
    provider = None
    try:
        candidate = get_provider(item.platform, get_settings())
        if candidate.capabilities(item.platform).get("detail"):
            provider = candidate
        elif isinstance(candidate, RedFoxProvider):
            await candidate.aclose()
    except ValueError:
        provider = None
    try:
        await get_body_text(db, item, provider=provider)
        await db.commit()
    finally:
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
    return FeedItemDetailOut(
        **serialize_feed_item(item, publisher),
        body_text=item.body_text,
        transcript_text=item.transcript_text,
    )

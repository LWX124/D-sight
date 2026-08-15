"""Unified subscription feed, discovery, detail, and refresh APIs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.social.body_fetch import get_body_text
from app.social.identity import ensure_publisher_identity
from app.social.provider_audit import audited_provider_call, provider_audit_name
from app.social.providers import PublisherDTO, get_provider
from app.social.providers.redfox import RedFoxProvider
from app.social.refresh import enqueue_publisher_refresh
from app.social.schemas import (
    FeedItemDetailOut,
    FeedItemOut,
    FeedPageOut,
    PublisherSearchOut,
    PublisherRefreshOut,
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


def _public_external_id(publisher: SocialPublisher) -> str:
    """Legacy WeChat fakeids are platform credentials, not a public API field."""

    return "" if publisher.provider == "wechat_mp" else publisher.external_id


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
) -> PublisherRefreshOut:
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

    queued = await enqueue_publisher_refresh(db, publisher)
    return PublisherRefreshOut(
        state=queued["state"],
        publisher_id=queued["publisher_id"],
        next_sync_at=(
            queued["next_sync_at"].isoformat() if queued["next_sync_at"] else None
        ),
    )


@router.post(
    "/publishers/{publisher_id}/refresh",
    response_model=PublisherRefreshOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_publisher_route(
    publisher_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublisherRefreshOut:
    return await _refresh_for_user(publisher_id, user, db)


@router.post(
    "/feed/refresh",
    include_in_schema=False,
    response_model=PublisherRefreshOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_feed_compat(
    publisher_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublisherRefreshOut:
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
            external_id=_public_external_id(publisher),
            name=publisher.name,
            avatar=publisher.avatar,
            enabled=subscription.enabled,
            provider=publisher.provider,
            sync_state=publisher.sync_state,
            sync_provider=publisher.sync_provider,
            last_synced_at=(publisher.last_synced_at.isoformat() if publisher.last_synced_at else None),
            last_sync_error_code=publisher.last_sync_error_code,
            last_sync_error=publisher.last_sync_error,
            next_sync_at=(publisher.next_sync_at.isoformat() if publisher.next_sync_at else None),
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
            "provider": body.provider,
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
                    provider=body.provider or "",
                ),
            )

    try:
        provider = get_provider(publisher.platform, get_settings())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    capabilities = provider.capabilities(publisher.platform)
    provider_name = provider_audit_name(provider)
    if publisher.platform == "wechat" and provider_name == "wechat_mp":
        raise HTTPException(422, "统一订阅仅接受 RedFox 搜索结果；微信补缺由平台调度")
    if publisher.provider and publisher.provider != provider_name:
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
        raise HTTPException(422, "发布者已绑定的 provider 当前不可用")
    if body.provider is not None and body.provider != provider_name:
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
        raise HTTPException(422, "provider 与当前可用采集源不匹配")
    if not publisher.provider:
        publisher.provider = provider_name
    await ensure_publisher_identity(
        db,
        publisher,
        provider=publisher.provider,
        external_id=publisher.external_id,
    )
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
        external_id=_public_external_id(publisher),
        name=publisher.name,
        avatar=publisher.avatar,
        enabled=subscription.enabled,
        provider=publisher.provider,
        sync_state=publisher.sync_state,
        sync_provider=publisher.sync_provider,
        last_synced_at=(publisher.last_synced_at.isoformat() if publisher.last_synced_at else None),
        last_sync_error_code=publisher.last_sync_error_code,
        last_sync_error=publisher.last_sync_error,
        next_sync_at=(publisher.next_sync_at.isoformat() if publisher.next_sync_at else None),
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
        effective_body_text = await get_body_text(db, item, provider=provider)
        await db.commit()
    finally:
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
    return FeedItemDetailOut(
        **serialize_feed_item(item, publisher),
        body_text=effective_body_text,
        transcript_text=item.transcript_text,
    )

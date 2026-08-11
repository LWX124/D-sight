"""Transactional consistency between legacy and unified social subscriptions."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.models import (
    WechatAccount,
    WechatSubscription,
    WeiboAccount,
    WeiboSubscription,
)
from app.social.providers.base import PublisherDTO
from app.social.unified import get_publisher_by_external, upsert_publisher
from app.social.unified_models import SocialPublisher, SocialSubscription


async def ensure_unified_subscription(
    db: AsyncSession,
    user_id: uuid.UUID,
    publisher_dto: PublisherDTO,
) -> tuple[SocialPublisher, SocialSubscription]:
    """Idempotently stage the unified half of a legacy subscription."""
    publisher = await upsert_publisher(db, publisher_dto)
    subscription = await ensure_subscription_for_publisher(db, user_id, publisher)
    return publisher, subscription


async def ensure_subscription_for_publisher(
    db: AsyncSession,
    user_id: uuid.UUID,
    publisher: SocialPublisher,
) -> SocialSubscription:
    """Idempotently stage a unified subscription to an existing publisher."""
    subscription_id = await db.scalar(
        pg_insert(SocialSubscription)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            publisher_id=publisher.id,
            enabled=True,
        )
        .on_conflict_do_update(
            constraint="uq_social_sub_user_publisher",
            set_={"enabled": True},
        )
        .returning(SocialSubscription.id)
    )
    subscription = await db.get(SocialSubscription, subscription_id)
    if subscription is None:  # pragma: no cover - protected by RETURNING
        raise RuntimeError("unified subscription upsert returned no row")
    return subscription


async def delete_legacy_subscription_pair(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    platform: str,
    external_id: str,
    legacy_subscription: WechatSubscription | WeiboSubscription,
) -> None:
    """Stage deletion of a legacy subscription and its unified projection."""
    publisher = await get_publisher_by_external(db, platform, external_id)
    if publisher is not None:
        unified = await db.scalar(
            select(SocialSubscription).where(
                SocialSubscription.user_id == user_id,
                SocialSubscription.publisher_id == publisher.id,
            )
        )
        if unified is not None:
            await db.delete(unified)
    await db.delete(legacy_subscription)


async def delete_unified_subscription_pair(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    subscription: SocialSubscription,
) -> None:
    """Stage unified deletion and remove the scheduler-driving legacy row."""
    publisher = await db.get(SocialPublisher, subscription.publisher_id)
    if publisher is None:
        await db.delete(subscription)
        return

    if publisher.platform == "weibo":
        account = await db.scalar(
            select(WeiboAccount).where(WeiboAccount.uid == publisher.external_id)
        )
        if account is not None:
            legacy = await db.scalar(
                select(WeiboSubscription).where(
                    WeiboSubscription.user_id == user_id,
                    WeiboSubscription.account_id == account.id,
                )
            )
            if legacy is not None:
                await db.delete(legacy)
    elif publisher.platform == "wechat" and publisher.provider == "wechat_mp":
        account = await db.scalar(
            select(WechatAccount).where(WechatAccount.fakeid == publisher.external_id)
        )
        if account is not None:
            legacy = await db.scalar(
                select(WechatSubscription).where(
                    WechatSubscription.user_id == user_id,
                    WechatSubscription.account_id == account.id,
                )
            )
            if legacy is not None:
                await db.delete(legacy)

    await db.delete(subscription)

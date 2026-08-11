"""Idempotently backfill WeChat and Weibo legacy rows into unified social tables.

Run from the repository root:
    uv run --project backend python scripts/migrate_social_data.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.social.models import (  # noqa: E402
    WechatAccount,
    WechatArticle,
    WechatSubscription,
    WeiboAccount,
    WeiboPost,
    WeiboSubscription,
)
from app.social.providers.base import PublisherDTO  # noqa: E402
from app.social.providers.wechat_mp import WechatMpProvider  # noqa: E402
from app.social.providers.weibo import WeiboProvider  # noqa: E402
from app.social.retention import CONTENT_BODY_RETENTION  # noqa: E402
from app.social.unified import upsert_item, upsert_publisher  # noqa: E402
from app.social.unified_models import (  # noqa: E402
    SocialItem,
    SocialPublisher,
    SocialSubscription,
)

async def _migrate_publishers(db: AsyncSession) -> dict[str, int]:
    counts = {"wechat": 0, "weibo": 0}
    for account in (await db.execute(select(WechatAccount))).scalars():
        publisher = await upsert_publisher(db, WechatMpProvider.from_wechat_account(account))
        publisher.platform_metadata = {
            **(publisher.platform_metadata or {}),
            "legacy_id": str(account.id),
            "fakeid": account.fakeid,
        }
        counts["wechat"] += 1
    for account in (await db.execute(select(WeiboAccount))).scalars():
        publisher = await upsert_publisher(
            db,
            PublisherDTO(
                platform="weibo",
                external_id=account.uid,
                name=account.name,
                avatar=account.avatar,
                description=account.description,
                profile_url=account.profile_url,
                provider="weibo",
                provider_ref=account.container_id,
                platform_metadata={
                    "legacy_id": str(account.id),
                    "uid": account.uid,
                    "container_id": account.container_id,
                },
            ),
        )
        publisher.last_synced_at = account.last_synced_at
        publisher.last_sync_status = account.last_sync_status
        publisher.last_sync_error = account.last_sync_error
        counts["weibo"] += 1
    return counts


async def _publisher_map(db: AsyncSession, platform: str) -> dict[str, SocialPublisher]:
    publishers = (
        await db.execute(select(SocialPublisher).where(SocialPublisher.platform == platform))
    ).scalars()
    return {publisher.external_id: publisher for publisher in publishers}


async def _migrate_items(db: AsyncSession) -> dict[str, int]:
    counts = {"wechat": 0, "weibo": 0}
    wechat_publishers = await _publisher_map(db, "wechat")
    wechat_accounts = {
        account.id: account for account in (await db.execute(select(WechatAccount))).scalars()
    }
    for article in (await db.execute(select(WechatArticle))).scalars():
        account = wechat_accounts.get(article.account_id)
        if account is None or account.fakeid not in wechat_publishers:
            raise RuntimeError(f"missing publisher for WeChat article {article.id}")
        dto = WechatMpProvider.from_wechat_article(article)
        dto.platform_metadata = {"legacy_id": str(article.id), "fakeid": account.fakeid}
        item = await upsert_item(db, dto, wechat_publishers[account.fakeid].id)
        if article.content_fetched_at:
            item.body_fetched_at = article.content_fetched_at
            item.body_expires_at = article.content_fetched_at + CONTENT_BODY_RETENTION
        counts["wechat"] += 1

    weibo_publishers = await _publisher_map(db, "weibo")
    weibo_accounts = {
        account.id: account for account in (await db.execute(select(WeiboAccount))).scalars()
    }
    for post in (await db.execute(select(WeiboPost))).scalars():
        account = weibo_accounts.get(post.account_id)
        if account is None or account.uid not in weibo_publishers:
            raise RuntimeError(f"missing publisher for Weibo post {post.id}")
        dto = WeiboProvider.from_weibo_post(post)
        dto.url = post.url
        dto.platform_metadata = {
            **dto.platform_metadata,
            "legacy_id": str(post.id),
            "container_id": account.container_id,
            "captured_at": post.captured_at.isoformat(),
        }
        item = await upsert_item(db, dto, weibo_publishers[account.uid].id)
        item.body_fetched_at = post.captured_at
        item.body_expires_at = post.captured_at + CONTENT_BODY_RETENTION
        counts["weibo"] += 1
    return counts


async def _migrate_subscriptions(db: AsyncSession) -> dict[str, int]:
    counts = {"wechat": 0, "weibo": 0}
    mappings = (
        (
            "wechat",
            WechatSubscription,
            {a.id: a for a in (await db.execute(select(WechatAccount))).scalars()},
            await _publisher_map(db, "wechat"),
            lambda account: account.fakeid,
        ),
        (
            "weibo",
            WeiboSubscription,
            {a.id: a for a in (await db.execute(select(WeiboAccount))).scalars()},
            await _publisher_map(db, "weibo"),
            lambda account: account.uid,
        ),
    )
    for platform, model, accounts, publishers, external_id_of in mappings:
        for subscription in (await db.execute(select(model))).scalars():
            account = accounts.get(subscription.account_id)
            if account is None:
                raise RuntimeError(f"missing account for {platform} subscription {subscription.id}")
            publisher = publishers.get(external_id_of(account))
            if publisher is None:
                raise RuntimeError(f"missing publisher for {platform} subscription {subscription.id}")
            await db.execute(
                pg_insert(SocialSubscription)
                .values(
                    user_id=subscription.user_id,
                    publisher_id=publisher.id,
                    enabled=subscription.enabled,
                    created_at=subscription.created_at,
                )
                .on_conflict_do_update(
                    constraint="uq_social_sub_user_publisher",
                    set_={"enabled": subscription.enabled},
                )
            )
            counts[platform] += 1
    return counts


async def verify_counts(db: AsyncSession) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    legacy_models = {
        "wechat": (WechatAccount, WechatArticle, WechatSubscription),
        "weibo": (WeiboAccount, WeiboPost, WeiboSubscription),
    }
    for platform, (account_model, item_model, subscription_model) in legacy_models.items():
        old = {
            "publishers": await db.scalar(select(func.count()).select_from(account_model)),
            "items": await db.scalar(select(func.count()).select_from(item_model)),
            "subscriptions": await db.scalar(select(func.count()).select_from(subscription_model)),
        }
        new = {
            "publishers": await db.scalar(
                select(func.count(SocialPublisher.id)).where(
                    SocialPublisher.platform == platform,
                    SocialPublisher.platform_metadata["legacy_id"].astext.is_not(None),
                )
            ),
            "items": await db.scalar(
                select(func.count(SocialItem.id)).where(
                    SocialItem.platform == platform,
                    SocialItem.platform_metadata["legacy_id"].astext.is_not(None),
                )
            ),
            "subscriptions": await db.scalar(
                select(func.count(SocialSubscription.id))
                .join(SocialPublisher, SocialSubscription.publisher_id == SocialPublisher.id)
                .where(
                    SocialPublisher.platform == platform,
                    SocialPublisher.platform_metadata["legacy_id"].astext.is_not(None),
                )
            ),
        }
        result[platform] = {
            "publishers": old["publishers"] == new["publishers"],
            "items": old["items"] == new["items"],
            # New users may legitimately subscribe to a migrated publisher
            # through the unified API after the backfill.
            "subscriptions": old["subscriptions"] <= new["subscriptions"],
        }
    return result


async def migrate(db: AsyncSession) -> dict[str, object]:
    publishers = await _migrate_publishers(db)
    items = await _migrate_items(db)
    subscriptions = await _migrate_subscriptions(db)
    await db.commit()
    counts = await verify_counts(db)
    return {
        "publishers": publishers,
        "items": items,
        "subscriptions": subscriptions,
        "counts": counts,
    }


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as db:
            result = await migrate(db)
        for platform in ("wechat", "weibo"):
            print(
                f"{platform}: publishers={result['publishers'][platform]}, "
                f"items={result['items'][platform]}, "
                f"subscriptions={result['subscriptions'][platform]}"
            )
            print(f"  reconciliation={result['counts'][platform]}")
        if not all(all(checks.values()) for checks in result["counts"].values()):
            raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

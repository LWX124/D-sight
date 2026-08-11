"""Reconcile WeChat and Weibo legacy data against unified social tables.

Run from the repository root:
    uv run --project backend python scripts/verify_social_migration.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from sqlalchemy import func, select  # noqa: E402
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
from app.social.unified_models import (  # noqa: E402
    SocialItem,
    SocialPublisher,
    SocialSubscription,
)

SAMPLE_SIZE = 50


def _same_time(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return abs((left - right).total_seconds()) <= 1


async def _counts(db: AsyncSession, platform: str, models: tuple[type, type, type]) -> dict:
    account_model, item_model, subscription_model = models
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
    matches = (
        old["publishers"] == new["publishers"]
        and old["items"] == new["items"]
        and old["subscriptions"] <= new["subscriptions"]
    )
    return {"old": old, "new": new, "matches": matches}


async def _verify_wechat_samples(db: AsyncSession) -> list[str]:
    errors: list[str] = []
    articles = (
        await db.execute(select(WechatArticle).order_by(func.random()).limit(SAMPLE_SIZE))
    ).scalars()
    for old in articles:
        new = await db.scalar(
            select(SocialItem).where(
                SocialItem.platform == "wechat",
                SocialItem.external_id == old.external_id,
            )
        )
        if new is None:
            errors.append(f"wechat item missing: {old.external_id}")
            continue
        if (
            new.title != old.title
            or new.body_text != old.content
            or new.url != old.url
            or not _same_time(new.published_at, old.published_at)
        ):
            errors.append(f"wechat item mismatch: {old.external_id}")
    accounts = (
        await db.execute(select(WechatAccount).order_by(func.random()).limit(SAMPLE_SIZE))
    ).scalars()
    for old in accounts:
        new = await db.scalar(
            select(SocialPublisher).where(
                SocialPublisher.platform == "wechat",
                SocialPublisher.external_id == old.fakeid,
            )
        )
        if new is None or (new.name, new.avatar, new.description) != (
            old.name,
            old.avatar,
            old.signature,
        ):
            errors.append(f"wechat publisher mismatch: {old.fakeid}")
    return errors


async def _verify_weibo_samples(db: AsyncSession) -> list[str]:
    errors: list[str] = []
    posts = (
        await db.execute(select(WeiboPost).order_by(func.random()).limit(SAMPLE_SIZE))
    ).scalars()
    for old in posts:
        new = await db.scalar(
            select(SocialItem).where(
                SocialItem.platform == "weibo",
                SocialItem.external_id == old.external_id,
            )
        )
        if new is None:
            errors.append(f"weibo item missing: {old.external_id}")
            continue
        if (
            new.body_text != old.content
            or new.url != old.url
            or not _same_time(new.published_at, old.published_at)
            or (new.platform_metadata or {}).get("bid") != old.bid
        ):
            errors.append(f"weibo item mismatch: {old.external_id}")
    accounts = (
        await db.execute(select(WeiboAccount).order_by(func.random()).limit(SAMPLE_SIZE))
    ).scalars()
    for old in accounts:
        new = await db.scalar(
            select(SocialPublisher).where(
                SocialPublisher.platform == "weibo",
                SocialPublisher.external_id == old.uid,
            )
        )
        if new is None or (new.name, new.avatar, new.description, new.profile_url) != (
            old.name,
            old.avatar,
            old.description,
            old.profile_url,
        ):
            errors.append(f"weibo publisher mismatch: {old.uid}")
    return errors


async def _verify_subscription_keys(
    db: AsyncSession,
    platform: str,
    subscription_model: type,
    account_model: type,
    account_external_column: Any,
) -> list[str]:
    old_rows = (
        await db.execute(
            select(
                subscription_model.user_id,
                account_external_column,
                subscription_model.enabled,
            ).join(account_model, subscription_model.account_id == account_model.id)
        )
    ).all()
    new_rows = (
        await db.execute(
            select(
                SocialSubscription.user_id,
                SocialPublisher.external_id,
                SocialSubscription.enabled,
            )
            .join(SocialPublisher, SocialSubscription.publisher_id == SocialPublisher.id)
            .where(SocialPublisher.platform == platform)
        )
    ).all()
    old_keys = {(str(user_id), external_id, enabled) for user_id, external_id, enabled in old_rows}
    new_keys = {(str(user_id), external_id, enabled) for user_id, external_id, enabled in new_rows}
    return [f"{platform} subscription missing: {key}" for key in sorted(old_keys - new_keys)]


async def verify(db: AsyncSession) -> list[dict]:
    platforms = (
        (
            "wechat",
            (WechatAccount, WechatArticle, WechatSubscription),
            _verify_wechat_samples,
            WechatSubscription,
            WechatAccount,
            WechatAccount.fakeid,
        ),
        (
            "weibo",
            (WeiboAccount, WeiboPost, WeiboSubscription),
            _verify_weibo_samples,
            WeiboSubscription,
            WeiboAccount,
            WeiboAccount.uid,
        ),
    )
    results = []
    for platform, models, sample_check, subscription_model, account_model, external_column in platforms:
        count_result = await _counts(db, platform, models)
        errors = await sample_check(db)
        errors.extend(
            await _verify_subscription_keys(
                db,
                platform,
                subscription_model,
                account_model,
                external_column,
            )
        )
        results.append(
            {
                "platform": platform,
                **count_result,
                "sample_size": SAMPLE_SIZE,
                "errors": errors,
                "ok": count_result["matches"] and not errors,
            }
        )
    return results


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as db:
            results = await verify(db)
        for result in results:
            marker = "PASS" if result["ok"] else "FAIL"
            print(f"{marker} {result['platform']}: old={result['old']} new={result['new']}")
            for error in result["errors"][:10]:
                print(f"  - {error}")
        if not all(result["ok"] for result in results):
            raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

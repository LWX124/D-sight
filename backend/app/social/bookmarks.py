"""Durable per-user social-content bookmarks."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.unified_models import (
    ContentBookmark,
    SocialItem,
    SocialPublisher,
    SocialSubscription,
)
from app.social.retention import CONTENT_BODY_RETENTION



async def bookmark_item(
    db: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    notes: str | None = None,
) -> ContentBookmark:
    """Create an idempotent bookmark and pin cached text against expiry."""
    item = await db.get(SocialItem, item_id)
    if item is None:
        raise LookupError("内容不存在")
    subscribed = await db.scalar(
        select(SocialSubscription.id)
        .where(
            SocialSubscription.user_id == user_id,
            SocialSubscription.publisher_id == item.publisher_id,
            SocialSubscription.enabled.is_(True),
        )
        .limit(1)
    )
    if subscribed is None:
        # Public AIHot provenance is the only visibility path outside a
        # user's subscriptions. Import locally to keep the social model usable
        # without loading the AIHot module during basic migrations.
        from app.aihot.models import HotItemSource, HotSourceMembership

        public_item = await db.scalar(
            select(HotItemSource.id)
            .join(
                HotSourceMembership,
                HotSourceMembership.id == HotItemSource.source_id,
            )
            .where(
                HotItemSource.item_id == item_id,
                HotSourceMembership.enabled.is_(True),
            )
            .limit(1)
        )
        if public_item is None:
            raise LookupError("内容不存在")
    bookmark = await db.scalar(
        select(ContentBookmark).where(
            ContentBookmark.user_id == user_id,
            ContentBookmark.item_id == item_id,
        )
    )
    if bookmark is None:
        bookmark = ContentBookmark(user_id=user_id, item_id=item_id, notes=notes)
        db.add(bookmark)
    elif notes is not None:
        bookmark.notes = notes

    # NULL expiry denotes durable retention while at least one bookmark exists.
    item.body_expires_at = None
    await db.flush()
    return bookmark


async def unbookmark_item(
    db: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
) -> bool:
    bookmark = await db.scalar(
        select(ContentBookmark).where(
            ContentBookmark.user_id == user_id,
            ContentBookmark.item_id == item_id,
        )
    )
    if bookmark is None:
        return False
    await db.delete(bookmark)
    await db.flush()
    remaining = await db.scalar(
        select(func.count(ContentBookmark.id)).where(ContentBookmark.item_id == item_id)
    )
    if not remaining:
        item = await db.get(SocialItem, item_id)
        if item is not None and (item.body_text or item.transcript_text):
            item.body_expires_at = datetime.now(timezone.utc) + CONTENT_BODY_RETENTION
    return True


async def list_bookmarks(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[dict]:
    rows = (
        await db.execute(
            select(ContentBookmark, SocialItem, SocialPublisher)
            .join(SocialItem, ContentBookmark.item_id == SocialItem.id)
            .join(SocialPublisher, SocialItem.publisher_id == SocialPublisher.id)
            .where(ContentBookmark.user_id == user_id)
            .order_by(ContentBookmark.created_at.desc(), ContentBookmark.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(bookmark.id),
            "item_id": str(item.id),
            "platform": item.platform,
            "title": item.title,
            "body_text": item.body_text,
            "transcript_text": item.transcript_text,
            "digest": item.digest,
            "cover_url": item.cover_url,
            "url": item.url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "publisher": {
                "id": str(publisher.id),
                "name": publisher.name,
                "avatar": publisher.avatar,
                "platform": publisher.platform,
            },
            "notes": bookmark.notes,
            "created_at": bookmark.created_at.isoformat(),
        }
        for bookmark, item, publisher in rows
    ]

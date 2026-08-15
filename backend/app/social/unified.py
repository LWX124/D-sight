"""Persistence and pagination for the unified social-content model."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.providers.base import ItemDTO, MetricsDTO, PublisherDTO
from app.social.retention import CONTENT_BODY_RETENTION
from app.social.unified_models import (
    ContentBookmark,
    SocialItem,
    SocialItemMetricSnapshot,
    SocialPublisher,
    SocialPublisherIdentity,
    SocialSubscription,
)

_NOT_LOADED = object()


def _non_empty(value: object) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


async def upsert_publisher(
    db: AsyncSession,
    dto: PublisherDTO,
    *,
    existing_publisher: SocialPublisher | None | object = _NOT_LOADED,
    flush: bool = True,
) -> SocialPublisher:
    """Insert or non-destructively update one platform publisher."""
    now = datetime.now(timezone.utc)
    publisher = existing_publisher
    if publisher is _NOT_LOADED or publisher is None:
        stmt = (
            pg_insert(SocialPublisher)
            .values(
                id=uuid.uuid4(),
                platform=dto.platform,
                external_id=dto.external_id,
                name=dto.name,
                avatar=dto.avatar,
                description=dto.description,
                profile_url=dto.profile_url,
                provider=dto.provider or None,
                provider_ref=dto.provider_ref,
                platform_metadata=dto.platform_metadata or {},
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_social_publishers_platform_ext")
            .returning(SocialPublisher.id)
        )
        inserted_id = (await db.execute(stmt)).scalar_one_or_none()
        publisher = (
            await db.get(SocialPublisher, inserted_id)
            if inserted_id
            else await get_publisher_by_external(db, dto.platform, dto.external_id)
        )
    if publisher is None:  # pragma: no cover - protects against an externally deleted conflict row
        raise RuntimeError("publisher upsert conflict could not be resolved")

    for field in ("name", "avatar", "description", "profile_url", "provider", "provider_ref"):
        value = getattr(dto, field)
        if _non_empty(value):
            setattr(publisher, field, value)
    publisher.platform_metadata = {
        **(publisher.platform_metadata or {}),
        **(dto.platform_metadata or {}),
    }
    publisher.updated_at = now
    if dto.provider:
        await db.execute(
            pg_insert(SocialPublisherIdentity)
            .values(
                id=uuid.uuid4(),
                publisher_id=publisher.id,
                platform=dto.platform,
                provider=dto.provider,
                external_id=dto.external_id,
                status="active",
                next_due_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                constraint="uq_social_identity_provider_platform_external"
            )
        )
        publisher.sync_provider = publisher.sync_provider or dto.provider
        publisher.next_sync_at = publisher.next_sync_at or now
    if flush:
        await db.flush()
    return publisher


def compute_content_hash(
    title: str | None,
    body_text: str | None,
    url: str | None,
) -> str | None:
    """Return a stable full SHA-256 fingerprint for meaningful content.

    A length-prefixed JSON tuple avoids boundary ambiguity while retaining the
    design contract's title/body/url inputs. Empty shells are not fingerprinted,
    otherwise every metadata-only item would collapse into one row.
    """
    values = [title or "", body_text or "", url or ""]
    if not any(value.strip() for value in values):
        return None
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compute_content_hash(dto: ItemDTO) -> str | None:
    return compute_content_hash(dto.title, dto.body_text, dto.url)


async def upsert_item(
    db: AsyncSession,
    dto: ItemDTO,
    publisher_id: uuid.UUID,
    *,
    existing_item: SocialItem | None | object = _NOT_LOADED,
    bookmarked: bool | None = None,
    flush: bool = True,
) -> SocialItem:
    """Insert or enrich content without overwriting stored text with blanks.

    Platform/external ID is the authoritative identity. A unique, full content
    hash supplies a stable duplicate signal without replacing the authoritative
    platform/external identity (complete legacy backfills must retain every ID).
    """
    now = datetime.now(timezone.utc)
    incoming_hash = _compute_content_hash(dto)
    item_id = uuid.uuid4()
    values = {
        "id": item_id,
        "publisher_id": publisher_id,
        "platform": dto.platform,
        "external_id": dto.external_id,
        "content_type": dto.content_type,
        "title": dto.title,
        "body_text": dto.body_text,
        "transcript_text": dto.transcript_text,
        "digest": dto.digest,
        "cover_url": dto.cover_url,
        "url": dto.url,
        "published_at": dto.published_at or now,
        "first_seen_at": now,
        "updated_at": now,
        "content_hash": incoming_hash,
        "platform_metadata": dto.platform_metadata or {},
    }
    if _non_empty(dto.body_text) or _non_empty(dto.transcript_text):
        values["body_fetched_at"] = now
        values["body_expires_at"] = now + CONTENT_BODY_RETENTION
    item = existing_item
    if item is _NOT_LOADED or item is None:
        inserted_id = (
            await db.execute(
                pg_insert(SocialItem)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_social_items_platform_ext")
                .returning(SocialItem.id)
            )
        ).scalar_one_or_none()

        if inserted_id:
            item = await db.get(SocialItem, inserted_id)
        else:
            item = await db.scalar(
                select(SocialItem).where(
                    SocialItem.platform == dto.platform,
                    SocialItem.external_id == dto.external_id,
                )
            )
    if item is None:  # pragma: no cover - protects against an externally deleted conflict row
        raise RuntimeError("item upsert conflict could not be resolved")

    for field in (
        "content_type",
        "title",
        "body_text",
        "transcript_text",
        "digest",
        "cover_url",
        "url",
    ):
        value = getattr(dto, field)
        if _non_empty(value):
            setattr(item, field, value)
    item.platform_metadata = {
        **(item.platform_metadata or {}),
        **(dto.platform_metadata or {}),
    }
    if dto.published_at is not None:
        item.published_at = dto.published_at
    item.updated_at = now
    if _non_empty(dto.body_text) or _non_empty(dto.transcript_text):
        item.body_fetched_at = now
        if bookmarked is None:
            bookmark_id = await db.scalar(
                select(ContentBookmark.id).where(ContentBookmark.item_id == item.id).limit(1)
            )
            bookmarked = bookmark_id is not None
        item.body_expires_at = None if bookmarked else now + CONTENT_BODY_RETENTION
    merged_hash = compute_content_hash(item.title, item.body_text, item.url)
    if merged_hash:
        item.content_hash = merged_hash
    if flush:
        await db.flush()
    return item


async def record_metrics(
    db: AsyncSession,
    item_id: uuid.UUID,
    dto: MetricsDTO,
    *,
    latest: SocialItemMetricSnapshot | None | object = _NOT_LOADED,
    flush: bool = True,
) -> SocialItemMetricSnapshot:
    """Append a changed metrics observation, skipping identical repeats."""
    if latest is _NOT_LOADED:
        latest = await db.scalar(
            select(SocialItemMetricSnapshot)
            .where(SocialItemMetricSnapshot.item_id == item_id)
            .order_by(
                desc(SocialItemMetricSnapshot.captured_at),
                desc(SocialItemMetricSnapshot.id),
            )
            .limit(1)
        )
    incoming = (
        dto.view_count,
        dto.like_count,
        dto.comment_count,
        dto.share_count,
        dto.collect_count,
        dto.provider_rank,
        dto.raw or {},
    )
    if latest is not None:
        previous = (
            latest.view_count,
            latest.like_count,
            latest.comment_count,
            latest.share_count,
            latest.collect_count,
            latest.provider_rank,
            latest.raw_metrics or {},
        )
        if incoming == previous:
            return latest
    snapshot = SocialItemMetricSnapshot(
        item_id=item_id,
        captured_at=datetime.now(timezone.utc),
        view_count=dto.view_count,
        like_count=dto.like_count,
        comment_count=dto.comment_count,
        share_count=dto.share_count,
        collect_count=dto.collect_count,
        provider_rank=dto.provider_rank,
        raw_metrics=dto.raw,
    )
    db.add(snapshot)
    if flush:
        await db.flush()
    return snapshot


def encode_feed_cursor(published_at: datetime, item_id: uuid.UUID) -> str:
    payload = json.dumps(
        [published_at.astimezone(timezone.utc).isoformat(), str(item_id)],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_feed_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        timestamp, item_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc), uuid.UUID(item_id)
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid feed cursor") from exc


def serialize_feed_item(item: SocialItem, publisher: SocialPublisher) -> dict:
    return {
        "id": str(item.id),
        "platform": item.platform,
        "external_id": item.external_id,
        "content_type": item.content_type,
        "title": item.title,
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
    }


async def get_feed(
    db: AsyncSession,
    user_id: uuid.UUID,
    publisher_id: uuid.UUID | None = None,
    before: tuple[datetime, uuid.UUID] | None = None,
    limit: int = 20,
) -> dict:
    """Return one strictly subscription-scoped, stable cursor page."""
    query = (
        select(SocialItem, SocialPublisher)
        .join(SocialPublisher, SocialItem.publisher_id == SocialPublisher.id)
        .join(
            SocialSubscription,
            and_(
                SocialSubscription.publisher_id == SocialItem.publisher_id,
                SocialSubscription.user_id == user_id,
                SocialSubscription.enabled.is_(True),
            ),
        )
    )
    if publisher_id:
        query = query.where(SocialItem.publisher_id == publisher_id)
    if before:
        before_at, before_id = before
        query = query.where(
            or_(
                SocialItem.published_at < before_at,
                and_(SocialItem.published_at == before_at, SocialItem.id < before_id),
            )
        )
    rows = (
        await db.execute(
            query.order_by(desc(SocialItem.published_at), desc(SocialItem.id)).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_before = None
    if has_more and page_rows:
        last_item = page_rows[-1][0]
        next_before = encode_feed_cursor(last_item.published_at, last_item.id)
    return {
        "items": [serialize_feed_item(item, publisher) for item, publisher in page_rows],
        "next_before": next_before,
    }


async def get_item_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
) -> tuple[SocialItem, SocialPublisher] | None:
    """Resolve a detail item visible through a subscription or durable bookmark."""
    visible = or_(
        SocialSubscription.id.is_not(None),
        ContentBookmark.id.is_not(None),
    )
    row = (
        await db.execute(
            select(SocialItem, SocialPublisher)
            .join(SocialPublisher, SocialItem.publisher_id == SocialPublisher.id)
            .outerjoin(
                SocialSubscription,
                and_(
                    SocialSubscription.publisher_id == SocialItem.publisher_id,
                    SocialSubscription.user_id == user_id,
                    SocialSubscription.enabled.is_(True),
                ),
            )
            .outerjoin(
                ContentBookmark,
                and_(ContentBookmark.item_id == SocialItem.id, ContentBookmark.user_id == user_id),
            )
            .where(SocialItem.id == item_id, visible)
        )
    ).one_or_none()
    return row


async def get_publisher_by_external(
    db: AsyncSession,
    platform: str,
    external_id: str,
) -> SocialPublisher | None:
    return await db.scalar(
        select(SocialPublisher).where(
            SocialPublisher.platform == platform,
            SocialPublisher.external_id == external_id,
        )
    )

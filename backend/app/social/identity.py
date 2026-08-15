"""Canonical publisher identity binding and transactional publisher merges."""

from __future__ import annotations

import unicodedata
import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.aihot.models import HotItemSource, HotSourceMembership
from app.social.ingest import get_or_create_account
from app.social.unified_models import (
    SocialItem,
    SocialPublisher,
    SocialPublisherIdentity,
    SocialSubscription,
)

logger = logging.getLogger(__name__)


def normalize_publisher_name(value: str) -> str:
    """Normalize spelling, but do not perform fuzzy or substring matching."""

    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


async def ensure_publisher_identity(
    db: AsyncSession,
    publisher: SocialPublisher,
    *,
    provider: str,
    external_id: str,
    status: str = "active",
    next_due_at: datetime | None = None,
) -> SocialPublisherIdentity:
    now = datetime.now(timezone.utc)
    identity_id = await db.scalar(
        pg_insert(SocialPublisherIdentity)
        .values(
            id=uuid.uuid4(),
            publisher_id=publisher.id,
            platform=publisher.platform,
            provider=provider,
            external_id=external_id,
            status=status,
            next_due_at=next_due_at or now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            constraint="uq_social_identity_provider_platform_external"
        )
        .returning(SocialPublisherIdentity.id)
    )
    identity = (
        await db.get(SocialPublisherIdentity, identity_id)
        if identity_id is not None
        else await db.scalar(
            select(SocialPublisherIdentity).where(
                SocialPublisherIdentity.provider == provider,
                SocialPublisherIdentity.platform == publisher.platform,
                SocialPublisherIdentity.external_id == external_id,
            )
        )
    )
    if identity is None:  # pragma: no cover - protected by the unique constraint
        raise RuntimeError("publisher identity conflict could not be resolved")
    return identity


async def merge_publishers(
    db: AsyncSession,
    canonical: SocialPublisher,
    duplicate: SocialPublisher,
) -> SocialPublisher:
    """Move durable references without rebuilding content/bookmark rows."""

    if canonical.id == duplicate.id:
        return canonical
    if canonical.platform != duplicate.platform:
        raise ValueError("publishers from different platforms cannot be merged")

    # Serialize merges in a deterministic order to avoid opposite-direction races.
    lock_key = ":".join(sorted((str(canonical.id), str(duplicate.id))))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"social-publisher-merge:{lock_key}"},
    )

    duplicate_subscriptions = (
        await db.execute(
            select(SocialSubscription).where(
                SocialSubscription.publisher_id == duplicate.id
            )
        )
    ).scalars().all()
    for subscription in duplicate_subscriptions:
        existing = await db.scalar(
            select(SocialSubscription).where(
                SocialSubscription.user_id == subscription.user_id,
                SocialSubscription.publisher_id == canonical.id,
            )
        )
        if existing is not None:
            existing.enabled = existing.enabled or subscription.enabled
            await db.delete(subscription)
        else:
            subscription.publisher_id = canonical.id

    await db.execute(
        update(SocialItem)
        .where(SocialItem.publisher_id == duplicate.id)
        .values(publisher_id=canonical.id)
    )

    canonical_source = await db.scalar(
        select(HotSourceMembership).where(
            HotSourceMembership.publisher_id == canonical.id
        )
    )
    duplicate_source = await db.scalar(
        select(HotSourceMembership).where(
            HotSourceMembership.publisher_id == duplicate.id
        )
    )
    if duplicate_source is not None and canonical_source is not None:
        links = (
            await db.execute(
                select(HotItemSource).where(
                    HotItemSource.source_id == duplicate_source.id
                )
            )
        ).scalars().all()
        for link in links:
            existing_link = await db.scalar(
                select(HotItemSource.id).where(
                    HotItemSource.item_id == link.item_id,
                    HotItemSource.source_id == canonical_source.id,
                )
            )
            if existing_link is not None:
                await db.delete(link)
            else:
                link.source_id = canonical_source.id
        await db.delete(duplicate_source)
    elif duplicate_source is not None:
        duplicate_source.publisher_id = canonical.id

    await db.execute(
        update(SocialPublisherIdentity)
        .where(SocialPublisherIdentity.publisher_id == duplicate.id)
        .values(publisher_id=canonical.id)
    )

    if canonical.last_synced_at is None or (
        duplicate.last_synced_at is not None
        and duplicate.last_synced_at > canonical.last_synced_at
    ):
        canonical.last_synced_at = duplicate.last_synced_at
        canonical.sync_state = duplicate.sync_state
        canonical.sync_provider = duplicate.sync_provider
        canonical.last_sync_status = duplicate.last_sync_status
        canonical.last_sync_error_code = duplicate.last_sync_error_code
        canonical.last_sync_error = duplicate.last_sync_error
    if canonical.next_sync_at is None or (
        duplicate.next_sync_at is not None
        and duplicate.next_sync_at < canonical.next_sync_at
    ):
        canonical.next_sync_at = duplicate.next_sync_at
    canonical.updated_at = datetime.now(timezone.utc)
    await db.delete(duplicate)
    await db.flush()
    return canonical


async def bind_publisher_identity(
    db: AsyncSession,
    publisher: SocialPublisher,
    *,
    provider: str,
    external_id: str,
    status: str = "active",
) -> tuple[SocialPublisher, SocialPublisherIdentity]:
    """Bind an upstream identity, merging its older publisher shell if needed."""

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"social-identity:{provider}:{publisher.platform}:{external_id}"},
    )
    identity = await db.scalar(
        select(SocialPublisherIdentity).where(
            SocialPublisherIdentity.provider == provider,
            SocialPublisherIdentity.platform == publisher.platform,
            SocialPublisherIdentity.external_id == external_id,
        )
    )
    if identity is not None and identity.publisher_id != publisher.id:
        duplicate = await db.get(SocialPublisher, identity.publisher_id)
        if duplicate is not None:
            publisher = await merge_publishers(db, publisher, duplicate)
    if identity is None:
        identity = await ensure_publisher_identity(
            db,
            publisher,
            provider=provider,
            external_id=external_id,
            status=status,
        )
    else:
        identity.publisher_id = publisher.id
        identity.status = status
        identity.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return publisher, identity


async def resolve_wechat_identity(
    db: AsyncSession,
    publisher: SocialPublisher,
    candidates: list[dict],
) -> tuple[str, SocialPublisherIdentity | None]:
    """Bind only one unique normalized exact-name match; never guess."""

    expected = normalize_publisher_name(publisher.name)
    matches: dict[str, dict] = {}
    for candidate in candidates:
        fakeid = str(candidate.get("fakeid") or "").strip()
        nickname = str(candidate.get("nickname") or "")
        if fakeid and normalize_publisher_name(nickname) == expected:
            matches[fakeid] = candidate

    now = datetime.now(timezone.utc)
    redfox_identity = await db.scalar(
        select(SocialPublisherIdentity).where(
            SocialPublisherIdentity.publisher_id == publisher.id,
            SocialPublisherIdentity.provider == "redfox",
        )
    )
    if not matches:
        logger.info("social identity unresolved publisher_id=%s", publisher.id)
        publisher.sync_state = "identity_unresolved"
        publisher.last_sync_error_code = "identity_unresolved"
        publisher.last_sync_error = "未找到名称完全一致的公众号"
        if redfox_identity is not None:
            redfox_identity.status = "identity_unresolved"
            redfox_identity.last_checked_at = now
        return "identity_unresolved", None
    if len(matches) > 1:
        logger.info(
            "social identity ambiguous publisher_id=%s matches=%d",
            publisher.id,
            len(matches),
        )
        publisher.sync_state = "identity_ambiguous"
        publisher.last_sync_error_code = "identity_ambiguous"
        publisher.last_sync_error = "找到多个名称完全一致的公众号，无法自动绑定"
        if redfox_identity is not None:
            redfox_identity.status = "identity_ambiguous"
            redfox_identity.last_checked_at = now
        return "identity_ambiguous", None

    fakeid, match = next(iter(matches.items()))
    await get_or_create_account(
        db,
        fakeid,
        str(match.get("nickname") or publisher.name),
        match.get("avatar"),
        match.get("signature"),
        commit=False,
    )
    publisher, identity = await bind_publisher_identity(
        db,
        publisher,
        provider="wechat_mp",
        external_id=fakeid,
    )
    logger.info(
        "social identity bound publisher_id=%s provider=wechat_mp", publisher.id
    )
    publisher.sync_state = "queued"
    publisher.sync_provider = "wechat_mp"
    publisher.last_sync_error_code = None
    publisher.last_sync_error = None
    identity.last_checked_at = now
    identity.next_due_at = now
    if redfox_identity is not None:
        redfox_identity.status = "coverage_gap"
        redfox_identity.last_checked_at = now
    return "queued", identity

"""Bounded retention for large social payloads; metadata and history stay intact."""

from datetime import datetime, timezone

from sqlalchemy import delete, exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.aihot.models import ProviderRawRecord
from app.social.bookmarks import ContentBookmark
from app.social.unified_models import SocialItem

_CLEANUP_LOCK_KEY = 2_024_081_013


async def cleanup_expired_content(db: AsyncSession) -> dict[str, int | str]:
    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _CLEANUP_LOCK_KEY}
    )
    if not acquired:
        return {"status": "already_running", "raw_deleted": 0, "bodies_cleared": 0}

    now = datetime.now(timezone.utc)
    raw_result = await db.execute(
        delete(ProviderRawRecord).where(ProviderRawRecord.expires_at <= now)
    )
    bookmarked = exists(
        select(ContentBookmark.id).where(ContentBookmark.item_id == SocialItem.id)
    )
    body_result = await db.execute(
        update(SocialItem)
        .where(
            SocialItem.body_expires_at.is_not(None),
            SocialItem.body_expires_at <= now,
            ~bookmarked,
        )
        .values(body_text=None, transcript_text=None, body_fetched_at=None, body_expires_at=None)
    )
    await db.commit()
    return {
        "status": "success",
        "raw_deleted": raw_result.rowcount or 0,
        "bodies_cleared": body_result.rowcount or 0,
    }

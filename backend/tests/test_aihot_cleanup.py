import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.aihot.cleanup import cleanup_expired_content
from app.aihot.models import ProviderRawRecord
from app.auth.models import User
from app.core.security import hash_password
from app.social.bookmarks import ContentBookmark
from app.social.unified_models import SocialItem, SocialPublisher


@pytest.mark.asyncio
async def test_cleanup_keeps_metadata_and_bookmarked_body(db_session):
    now = datetime.now(timezone.utc)
    user = User(
        email=f"cleanup-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"cleanup-{uuid.uuid4()}",
        name="清理测试",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([user, publisher])
    await db_session.flush()

    def item(title: str) -> SocialItem:
        return SocialItem(
            publisher_id=publisher.id,
            platform="wechat",
            external_id=f"item-{uuid.uuid4()}",
            content_type="article",
            title=title,
            body_text="大正文",
            transcript_text="大字幕",
            published_at=now,
            body_fetched_at=now - timedelta(days=91),
            body_expires_at=now - timedelta(days=1),
            platform_metadata={},
        )

    ordinary = item("普通内容")
    bookmarked = item("已收藏内容")
    db_session.add_all([ordinary, bookmarked])
    await db_session.flush()
    db_session.add_all(
        [
            ContentBookmark(user_id=user.id, item_id=bookmarked.id),
            ProviderRawRecord(
                provider="redfox",
                platform="wechat",
                operation="test",
                payload={"large": "payload"},
                expires_at=now - timedelta(seconds=1),
            ),
            ProviderRawRecord(
                provider="redfox",
                platform="wechat",
                operation="test",
                payload={"keep": True},
                expires_at=now + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    result = await cleanup_expired_content(db_session)
    await db_session.refresh(ordinary)
    await db_session.refresh(bookmarked)
    raw_rows = list((await db_session.execute(select(ProviderRawRecord))).scalars())
    assert result["bodies_cleared"] == 1
    assert result["raw_deleted"] == 1
    assert ordinary.title == "普通内容"
    assert ordinary.body_text is None and ordinary.transcript_text is None
    assert bookmarked.body_text == "大正文" and bookmarked.transcript_text == "大字幕"
    assert len(raw_rows) == 1 and raw_rows[0].payload == {"keep": True}

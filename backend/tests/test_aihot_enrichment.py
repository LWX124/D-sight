import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.aihot.enrichment import ENRICHMENT_VERSION, enrich_pending_items
from app.aihot.models import ContentEnrichment, HotItemSource, HotSourceMembership
from app.auth.models import User
from app.core.security import hash_password
from app.social.unified_models import SocialItem, SocialPublisher


@pytest.mark.asyncio
async def test_enrichment_is_async_metadata_not_a_heat_score(db_session, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "true")
    from app.core import config

    config.get_settings.cache_clear()
    owner = User(
        email=f"enrichment-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="bilibili",
        external_id=f"mid-{uuid.uuid4()}",
        name="金融作者",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([owner, publisher])
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="bilibili",
        external_id=f"bv-{uuid.uuid4()}",
        content_type="video",
        title="央行利率政策影响股票市场",
        published_at=datetime.now(timezone.utc),
        first_seen_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        content_hash=uuid.uuid4().hex,
        platform_metadata={},
    )
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="bilibili",
        category="policy",
        added_by=owner.id,
    )
    db_session.add_all([item, source])
    await db_session.flush()
    db_session.add(HotItemSource(item_id=item.id, source_id=source.id))
    await db_session.commit()

    result = await enrich_pending_items(db_session)
    enrichment = await db_session.scalar(
        select(ContentEnrichment).where(
            ContentEnrichment.item_id == item.id,
            ContentEnrichment.version == ENRICHMENT_VERSION,
        )
    )
    assert result == {"status": "success", "processed": 1, "failed": 0}
    assert enrichment is not None
    assert enrichment.model == "fake"
    assert enrichment.status == "done"
    assert enrichment.is_financial is True
    assert enrichment.category == "policy"
    assert not hasattr(enrichment, "aihot_score")
    config.get_settings.cache_clear()

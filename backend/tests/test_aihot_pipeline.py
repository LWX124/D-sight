import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from app.aihot.models import HotItemSource, HotRanking, HotRun, HotSourceMembership
from app.aihot.pipeline import FetchResult, _compute_rankings, run_aihot_batch
from app.aihot.ranking import FORMULA_VERSION
from app.auth.models import User
from app.core.db import get_engine, get_sessionmaker
from app.core.security import hash_password
from app.social.providers.base import ItemDTO, MetricsDTO
from app.social.unified_models import (
    SocialItem,
    SocialItemMetricSnapshot,
    SocialPublisher,
)


@pytest.mark.asyncio
async def test_private_subscription_content_cannot_enter_public_aihot(db_session):
    now = datetime.now(timezone.utc)
    owner = User(
        email=f"hot-owner-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    public_publisher = SocialPublisher(
        platform="wechat",
        external_id=f"public-{uuid.uuid4()}",
        name="公共金融信源",
        platform_metadata={},
    )
    private_publisher = SocialPublisher(
        platform="wechat",
        external_id=f"private-{uuid.uuid4()}",
        name="用户私有订阅",
        platform_metadata={},
    )
    db_session.add_all([owner, public_publisher, private_publisher])
    await db_session.flush()
    public_item = SocialItem(
        publisher_id=public_publisher.id,
        platform="wechat",
        external_id=f"public-item-{uuid.uuid4()}",
        content_type="article",
        title="公共内容",
        published_at=now,
        platform_metadata={},
    )
    private_item = SocialItem(
        publisher_id=private_publisher.id,
        platform="wechat",
        external_id=f"private-item-{uuid.uuid4()}",
        content_type="article",
        title="私人订阅内容",
        published_at=now,
        platform_metadata={},
    )
    source = HotSourceMembership(
        publisher_id=public_publisher.id,
        platform="wechat",
        category="market",
        added_by=owner.id,
    )
    run = HotRun(
        platform="all",
        status="running",
        run_type="scheduled",
        formula_version=FORMULA_VERSION,
        started_at=now,
    )
    db_session.add_all([public_item, private_item, source, run])
    await db_session.flush()
    db_session.add_all(
        [
            HotItemSource(item_id=public_item.id, source_id=source.id),
            SocialItemMetricSnapshot(
                item_id=public_item.id, captured_at=now, like_count=1, raw_metrics={}
            ),
            SocialItemMetricSnapshot(
                item_id=private_item.id,
                captured_at=now,
                like_count=1_000_000,
                raw_metrics={},
            ),
        ]
    )
    await db_session.flush()

    await _compute_rankings(db_session, run.id, now)
    ranked_ids = set(
        (
            await db_session.execute(
                select(HotRanking.item_id).where(HotRanking.run_id == run.id)
            )
        ).scalars()
    )
    assert public_item.id in ranked_ids
    assert private_item.id not in ranked_ids


@pytest.mark.asyncio
async def test_aihot_provider_failure_never_persists_or_returns_api_key(
    db_session, monkeypatch
):
    secret = f"redfox-secret-{uuid.uuid4()}"
    owner = User(
        email=f"hot-secret-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"secret-source-{uuid.uuid4()}",
        name="脱敏信源",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([owner, publisher])
    await db_session.flush()
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="wechat",
        provider="redfox",
        category="market",
        added_by=owner.id,
    )
    db_session.add(source)
    await db_session.commit()

    async def fail_sources(provider, sources):
        del provider, sources
        return [
            FetchResult(
                membership=source,
                publisher=publisher,
                items=[],
                elapsed_ms=1,
                error=RuntimeError(f"api_key={secret}"),
            )
        ]

    monkeypatch.setattr("app.aihot.pipeline._fetch_sources", fail_sources)
    result = await run_aihot_batch(db_session, secret, run_type="test")

    run = await db_session.get(HotRun, uuid.UUID(result["run_id"]))
    assert result["status"] == "failed"
    assert secret not in str(result)
    assert run is not None
    assert secret not in (run.error_message or "")


@pytest.mark.asyncio
async def test_aihot_ingestion_bulk_loads_state_and_batches_provenance(
    db_session, monkeypatch
):
    owner = User(
        email=f"hot-query-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"query-source-{uuid.uuid4()}",
        name="批量查询信源",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([owner, publisher])
    await db_session.flush()
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="wechat",
        provider="redfox",
        category="market",
        added_by=owner.id,
    )
    db_session.add(source)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    items = [
        SocialItem(
            publisher_id=publisher.id,
            platform="wechat",
            external_id=f"bulk-{uuid.uuid4()}",
            content_type="article",
            title=f"批量内容 {index}",
            published_at=now,
            platform_metadata={},
        )
        for index in range(4)
    ]
    db_session.add_all(items)
    await db_session.flush()
    db_session.add_all(
        [
            SocialItemMetricSnapshot(
                item_id=item.id,
                captured_at=now,
                like_count=index,
                raw_metrics={},
            )
            for index, item in enumerate(items)
        ]
    )
    source_id = source.id
    await db_session.commit()

    dtos = [
        ItemDTO(
            platform="wechat",
            external_id=item.external_id,
            content_type="article",
            title=item.title,
            published_at=now,
            metrics=MetricsDTO(like_count=index),
        )
        for index, item in enumerate(items)
    ]

    async def fetched(provider, sources):
        del provider
        target = next(source for source in sources if source.id == source_id)
        return [FetchResult(target, target.publisher, dtos, elapsed_ms=1)]

    async def no_rankings(db, run_id, captured_at):
        del db, run_id, captured_at

    monkeypatch.setattr("app.aihot.pipeline._fetch_sources", fetched)
    monkeypatch.setattr("app.aihot.pipeline._compute_rankings", no_rankings)
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await run_aihot_batch(db_session, "test-key", run_type="query-count")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert result["status"] == "success"
    assert result["updated"] == len(items)
    assert len([sql for sql in statements if "INSERT INTO hot_item_sources" in sql]) == 1
    assert not [
        sql
        for sql in statements
        if "FROM social_item_metric_snapshots" in sql
        and "social_item_metric_snapshots.item_id =" in sql
    ]
    identity_loads = [
        sql
        for sql in statements
        if "FROM social_items" in sql
        and "social_items.platform" in sql
        and " IN (" in sql
    ]
    assert len(identity_loads) == 1
    assert await db_session.scalar(
        select(func.count(HotItemSource.id)).where(HotItemSource.source_id == source_id)
    ) == len(items)


@pytest.mark.asyncio
async def test_aihot_bulk_path_keeps_malformed_item_savepoint_isolation(
    db_session, monkeypatch
):
    owner = User(
        email=f"hot-isolation-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"isolation-source-{uuid.uuid4()}",
        name="隔离信源",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([owner, publisher])
    await db_session.flush()
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="wechat",
        provider="redfox",
        category="market",
        added_by=owner.id,
    )
    db_session.add(source)
    await db_session.flush()
    source_id = source.id
    await db_session.commit()
    good_external_id = f"good-{uuid.uuid4()}"
    dtos = [
        ItemDTO(
            platform="wechat",
            external_id="x" * 129,
            content_type="article",
            title="坏记录",
            published_at=datetime.now(timezone.utc),
        ),
        ItemDTO(
            platform="wechat",
            external_id=good_external_id,
            content_type="article",
            title="好记录",
            published_at=datetime.now(timezone.utc),
        ),
    ]

    async def fetched(provider, sources):
        del provider
        target = next(source for source in sources if source.id == source_id)
        return [FetchResult(target, target.publisher, dtos, elapsed_ms=1)]

    async def no_rankings(db, run_id, captured_at):
        del db, run_id, captured_at

    monkeypatch.setattr("app.aihot.pipeline._fetch_sources", fetched)
    monkeypatch.setattr("app.aihot.pipeline._compute_rankings", no_rankings)
    result = await run_aihot_batch(db_session, "test-key", run_type="isolation")

    assert result["status"] == "partial"
    assert result["fetched"] == 1 and len(result["errors"]) == 1
    good = await db_session.scalar(
        select(SocialItem).where(
            SocialItem.platform == "wechat",
            SocialItem.external_id == good_external_id,
        )
    )
    assert good is not None
    assert await db_session.scalar(
        select(func.count(HotItemSource.id)).where(
            HotItemSource.item_id == good.id,
            HotItemSource.source_id == source_id,
        )
    ) == 1


@pytest.mark.asyncio
async def test_aihot_discards_source_disabled_during_provider_io(
    db_session, monkeypatch
):
    owner = User(
        email=f"hot-concurrent-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"concurrent-source-{uuid.uuid4()}",
        name="并发停用信源",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([owner, publisher])
    await db_session.flush()
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="wechat",
        provider="redfox",
        category="market",
        added_by=owner.id,
    )
    db_session.add(source)
    await db_session.commit()
    source_id = source.id
    external_id = f"discarded-{uuid.uuid4()}"

    async def fetched(provider, sources):
        del provider
        target = next(candidate for candidate in sources if candidate.id == source_id)
        async with get_sessionmaker()() as concurrent_db:
            current = await concurrent_db.get(HotSourceMembership, source_id)
            current.enabled = False
            current.updated_at = datetime.now(timezone.utc)
            await concurrent_db.commit()
        return [
            FetchResult(
                target,
                target.publisher,
                [
                    ItemDTO(
                        platform="wechat",
                        external_id=external_id,
                        content_type="article",
                        title="停用后不应入库",
                        published_at=datetime.now(timezone.utc),
                    )
                ],
                elapsed_ms=1,
            )
        ]

    monkeypatch.setattr("app.aihot.pipeline._fetch_sources", fetched)
    result = await run_aihot_batch(db_session, "test-key", run_type="source-disabled")

    assert result["status"] == "empty"
    assert await db_session.scalar(
        select(SocialItem.id).where(
            SocialItem.platform == "wechat",
            SocialItem.external_id == external_id,
        )
    ) is None


@pytest.mark.asyncio
async def test_aihot_existing_item_recovers_after_savepoint_flush_failure(
    db_session, monkeypatch
):
    owner = User(
        email=f"hot-savepoint-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"savepoint-source-{uuid.uuid4()}",
        name="Savepoint 信源",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add_all([owner, publisher])
    await db_session.flush()
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="wechat",
        provider="redfox",
        category="market",
        added_by=owner.id,
    )
    existing = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"savepoint-item-{uuid.uuid4()}",
        content_type="article",
        title="旧标题",
        published_at=datetime.now(timezone.utc),
        platform_metadata={},
    )
    db_session.add_all([source, existing])
    await db_session.commit()
    source_id = source.id
    existing_id = existing.id
    existing_external_id = existing.external_id

    async def fetched(provider, sources):
        del provider
        target = next(candidate for candidate in sources if candidate.id == source_id)
        common = {
            "platform": "wechat",
            "external_id": existing_external_id,
            "published_at": datetime.now(timezone.utc),
        }
        return [
            FetchResult(
                target,
                target.publisher,
                [
                    ItemDTO(**common, content_type="x" * 129, title="非法更新"),
                    ItemDTO(**common, content_type="article", title="恢复后的标题"),
                ],
                elapsed_ms=1,
            )
        ]

    async def no_rankings(db, run_id, captured_at):
        del db, run_id, captured_at

    monkeypatch.setattr("app.aihot.pipeline._fetch_sources", fetched)
    monkeypatch.setattr("app.aihot.pipeline._compute_rankings", no_rankings)
    result = await run_aihot_batch(db_session, "test-key", run_type="savepoint")

    recovered = await db_session.get(SocialItem, existing_id)
    assert result["status"] == "partial"
    assert result["fetched"] == 1
    assert recovered.content_type == "article"
    assert recovered.title == "恢复后的标题"

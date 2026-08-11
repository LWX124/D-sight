"""Reliable AIHot ingestion and ranking snapshots."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, desc, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.aihot.models import (
    ContentEnrichment,
    HotItemSource,
    HotRanking,
    HotRun,
    HotSourceMembership,
    ProviderCallLog,
    ProviderRawRecord,
)
from app.aihot.ranking import FORMULA_VERSION, rank_items
from app.core.config import get_settings
from app.core.db import get_engine
from app.social.provider_audit import redact_secret_text, sanitize_provider_payload
from app.social.providers.base import ItemDTO, PublisherDTO
from app.social.providers.redfox import RedFoxProvider
from app.social.retention import PROVIDER_RAW_RETENTION
from app.social.unified import record_metrics, upsert_item, upsert_publisher
from app.social.unified_models import (
    ContentBookmark,
    SocialItem,
    SocialItemMetricSnapshot,
    SocialPublisher,
)

logger = logging.getLogger(__name__)

_BATCH_LOCK_KEY = 2_024_081_011
_SUPPORTED_PLATFORMS = {"wechat", "xiaohongshu", "bilibili"}
ENRICHMENT_VERSION = "finance-v1"
_DEFAULT_SEARCH_TERMS = {
    "macro": "宏观经济",
    "policy": "金融政策",
    "industry": "产业投资",
    "company": "上市公司",
    "market": "股票市场",
}


@dataclass
class FetchResult:
    membership: HotSourceMembership | "SourceSpec"
    publisher: SocialPublisher | PublisherDTO | None
    items: list[ItemDTO]
    elapsed_ms: int
    error: Exception | None = None


@dataclass(frozen=True)
class SourceSpec:
    """Detached source input so provider I/O never holds a DB transaction."""

    id: uuid.UUID
    platform: str
    category: str
    source_key: str | None
    publisher_id: uuid.UUID | None
    publisher: PublisherDTO | None
    updated_at: datetime


@dataclass
class IngestionCache:
    items: dict[tuple[str, str], SocialItem]
    publishers: dict[str, SocialPublisher]
    latest_metrics: dict[uuid.UUID, SocialItemMetricSnapshot]
    bookmarked_item_ids: set[uuid.UUID]
    provenance: set[tuple[uuid.UUID, uuid.UUID]]


def _publisher_dto(publisher: SocialPublisher) -> PublisherDTO:
    return PublisherDTO(
        platform=publisher.platform,
        external_id=publisher.external_id,
        name=publisher.name,
        avatar=publisher.avatar,
        description=publisher.description,
        profile_url=publisher.profile_url,
        provider=publisher.provider or "redfox",
        provider_ref=publisher.provider_ref,
        platform_metadata=publisher.platform_metadata or {},
    )


def _xhs_author_dto(dto: ItemDTO) -> PublisherDTO | None:
    """Resolve a discovered XHS author without inventing cross-provider identity."""
    metadata = dto.platform_metadata or {}
    external_id = str(metadata.get("account_userid") or "").strip()
    if not external_id:
        return None
    return PublisherDTO(
        platform="xiaohongshu",
        external_id=external_id,
        name=metadata.get("account_nickname") or external_id,
        provider="redfox",
        platform_metadata={"discovered_by": "aihot_search"},
    )


async def _load_source_specs(db: AsyncSession) -> list[SourceSpec]:
    rows = (
        await db.execute(
            select(HotSourceMembership, SocialPublisher)
            .outerjoin(SocialPublisher, HotSourceMembership.publisher_id == SocialPublisher.id)
            .where(
                HotSourceMembership.enabled.is_(True),
                HotSourceMembership.platform.in_(_SUPPORTED_PLATFORMS),
                HotSourceMembership.provider == "redfox",
            )
        )
    ).all()
    return [
        SourceSpec(
            id=membership.id,
            platform=membership.platform,
            category=membership.category,
            source_key=membership.source_key,
            publisher_id=membership.publisher_id,
            publisher=_publisher_dto(publisher) if publisher is not None else None,
            updated_at=membership.updated_at,
        )
        for membership, publisher in rows
    ]


async def _current_source_results(
    db: AsyncSession,
    fetched_results: list[FetchResult],
) -> list[FetchResult]:
    """Discard results for sources changed while provider I/O was in flight."""
    specs = {
        result.membership.id: result.membership
        for result in fetched_results
        if isinstance(result.membership, SourceSpec)
    }
    if not specs:
        return fetched_results
    memberships = (
        await db.execute(
            select(HotSourceMembership).where(
                HotSourceMembership.id.in_(specs),
                HotSourceMembership.enabled.is_(True),
                HotSourceMembership.provider == "redfox",
            ).with_for_update()
        )
    ).scalars()
    current_ids = {
        membership.id
        for membership in memberships
        if membership.updated_at == specs[membership.id].updated_at
    }
    return [
        result for result in fetched_results if result.membership.id in current_ids
    ]


async def _load_ingestion_cache(
    db: AsyncSession,
    fetched_results: list[FetchResult],
) -> IngestionCache:
    """Bulk-load every identity/read model used by the per-record savepoints."""
    item_keys = {
        (dto.platform, dto.external_id)
        for result in fetched_results
        if result.error is None
        for dto in result.items
        if dto.external_id
    }
    items: dict[tuple[str, str], SocialItem] = {}
    if item_keys:
        loaded_items = (
            await db.execute(
                select(SocialItem).where(
                    tuple_(SocialItem.platform, SocialItem.external_id).in_(item_keys)
                )
            )
        ).scalars()
        items = {(item.platform, item.external_id): item for item in loaded_items}

    author_ids = {
        author.external_id
        for result in fetched_results
        if result.error is None
        for dto in result.items
        if dto.platform == "xiaohongshu"
        if (author := _xhs_author_dto(dto)) is not None
    }
    publishers: dict[str, SocialPublisher] = {}
    if author_ids:
        loaded_publishers = (
            await db.execute(
                select(SocialPublisher).where(
                    SocialPublisher.platform == "xiaohongshu",
                    SocialPublisher.external_id.in_(author_ids),
                )
            )
        ).scalars()
        publishers = {publisher.external_id: publisher for publisher in loaded_publishers}

    item_ids = {item.id for item in items.values()}
    latest_metrics: dict[uuid.UUID, SocialItemMetricSnapshot] = {}
    bookmarked_item_ids: set[uuid.UUID] = set()
    provenance: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if item_ids:
        metrics = (
            await db.execute(
                select(SocialItemMetricSnapshot)
                .where(SocialItemMetricSnapshot.item_id.in_(item_ids))
                .distinct(SocialItemMetricSnapshot.item_id)
                .order_by(
                    SocialItemMetricSnapshot.item_id,
                    desc(SocialItemMetricSnapshot.captured_at),
                    desc(SocialItemMetricSnapshot.id),
                )
            )
        ).scalars()
        latest_metrics = {metric.item_id: metric for metric in metrics}
        bookmarked_item_ids = set(
            (
                await db.execute(
                    select(ContentBookmark.item_id).where(
                        ContentBookmark.item_id.in_(item_ids)
                    )
                )
            ).scalars()
        )
        source_ids = {result.membership.id for result in fetched_results}
        provenance = set(
            (
                await db.execute(
                    select(HotItemSource.item_id, HotItemSource.source_id).where(
                        HotItemSource.item_id.in_(item_ids),
                        HotItemSource.source_id.in_(source_ids),
                    )
                )
            ).all()
        )
    return IngestionCache(
        items=items,
        publishers=publishers,
        latest_metrics=latest_metrics,
        bookmarked_item_ids=bookmarked_item_ids,
        provenance=provenance,
    )


async def _prepare_xhs_publishers(
    db: AsyncSession,
    fetched_results: list[FetchResult],
    cache: IngestionCache,
) -> tuple[dict[str, uuid.UUID], dict[str, Exception]]:
    """Upsert each discovered XHS author once, retaining per-author isolation."""
    author_dtos: dict[str, PublisherDTO] = {}
    for result in fetched_results:
        if result.error is not None:
            continue
        for dto in result.items:
            if dto.platform != "xiaohongshu":
                continue
            author = _xhs_author_dto(dto)
            if author is not None:
                author_dtos[author.external_id] = author

    publisher_ids: dict[str, uuid.UUID] = {}
    errors: dict[str, Exception] = {}
    for external_id, dto in author_dtos.items():
        try:
            async with db.begin_nested():
                publisher = await upsert_publisher(
                    db,
                    dto,
                    existing_publisher=cache.publishers.get(external_id),
                    flush=False,
                )
            cache.publishers[external_id] = publisher
            publisher_ids[external_id] = publisher.id
        except Exception as exc:
            errors[external_id] = exc
    return publisher_ids, errors


def _publisher_id_for_item(
    result: FetchResult,
    dto: ItemDTO,
    xhs_publisher_ids: dict[str, uuid.UUID],
) -> uuid.UUID | None:
    if dto.platform == "xiaohongshu":
        author = _xhs_author_dto(dto)
        if author is not None:
            return xhs_publisher_ids.get(author.external_id)
    publisher_id = getattr(result.membership, "publisher_id", None)
    if publisher_id is not None:
        return publisher_id
    return getattr(result.publisher, "id", None)


async def _fetch_sources(
    provider: RedFoxProvider,
    sources: list[SourceSpec],
) -> list[FetchResult]:
    semaphore = asyncio.Semaphore(3)

    async def fetch_one(source: SourceSpec) -> FetchResult:
        started = time.perf_counter()
        try:
            async with semaphore:
                if source.platform == "xiaohongshu":
                    vertical_fetch = getattr(provider, "fetch_vertical_hot_feed", None)
                    if vertical_fetch is None:
                        raise RuntimeError("RedFox provider does not support xiaohongshu search feed")
                    items = await vertical_fetch(
                        platform="xiaohongshu",
                        source_key=(
                            source.source_key
                            or _DEFAULT_SEARCH_TERMS.get(source.category, "金融 股票 政策")
                        ),
                        window="7d",
                    )
                else:
                    if source.publisher is None:
                        raise RuntimeError("account source is missing its publisher")
                    items = await provider.fetch_publisher_items(source.publisher)
            return FetchResult(
                source,
                source.publisher,
                items,
                int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # provider failures are isolated per source
            return FetchResult(
                source,
                source.publisher,
                [],
                int((time.perf_counter() - started) * 1000),
                exc,
            )

    return await asyncio.gather(*(fetch_one(source) for source in sources))


async def run_aihot_batch(
    db: AsyncSession,
    redfox_api_key: str,
    run_type: str = "scheduled",
) -> dict:
    """Execute one globally deduplicated batch without a network-long DB transaction."""
    if db.in_transaction():
        # API authentication and scheduler setup may leave a read transaction
        # open. No caller-owned writes are part of the batch contract.
        await db.rollback()

    async with get_engine().connect() as lock_connection:
        acquired = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _BATCH_LOCK_KEY}
        )
        await lock_connection.commit()
        if not acquired:
            return {"status": "already_running"}
        try:
            return await _run_locked_batch(db, redfox_api_key, run_type)
        finally:
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": _BATCH_LOCK_KEY}
            )
            await lock_connection.commit()


async def _run_locked_batch(
    db: AsyncSession,
    redfox_api_key: str,
    run_type: str,
) -> dict:
    """Run provider I/O under a session lock and persist in one short transaction."""

    now = datetime.now(timezone.utc)
    try:
        source_specs = await _load_source_specs(db)
        await db.rollback()
        if not source_specs:
            empty_run = HotRun(
                platform="all",
                provider="redfox",
                run_type=run_type,
                status="empty",
                started_at=now,
                finished_at=datetime.now(timezone.utc),
                formula_version=FORMULA_VERSION,
            )
            db.add(empty_run)
            await db.commit()
            return {"status": "empty", "fetched": 0, "new": 0, "updated": 0, "errors": []}

        provider = RedFoxProvider(api_key=redfox_api_key)
        try:
            fetched_results = await _fetch_sources(provider, source_specs)
        finally:
            await provider.aclose()

        run = HotRun(
            platform="all",
            provider="redfox",
            run_type=run_type,
            status="running",
            started_at=now,
            formula_version=FORMULA_VERSION,
        )
        db.add(run)
        await db.flush()
        for raw_record in provider.drain_raw_records():
            db.add(
                ProviderRawRecord(
                    provider="redfox",
                    platform=raw_record["platform"],
                    operation=raw_record["operation"],
                    payload=sanitize_provider_payload(
                        raw_record["payload"],
                        (redfox_api_key,),
                    ),
                    expires_at=now + PROVIDER_RAW_RETENTION,
                )
            )
        total_fetched = total_new = total_updated = 0
        errors: list[str] = []
        current_results = await _current_source_results(db, fetched_results)
        current_source_ids = {result.membership.id for result in current_results}
        cache = await _load_ingestion_cache(db, current_results)
        xhs_publisher_ids, xhs_publisher_errors = await _prepare_xhs_publishers(
            db,
            current_results,
            cache,
        )
        known_item_keys = set(cache.items)
        pending_provenance: set[tuple[uuid.UUID, uuid.UUID]] = set()

        for result in fetched_results:
            operation = (
                "search_vertical_feed"
                if result.membership.platform == "xiaohongshu"
                else "fetch_publisher_items"
            )
            db.add(
                ProviderCallLog(
                    provider="redfox",
                    platform=result.membership.platform,
                    endpoint=operation,
                    operation=operation,
                    status="failed" if result.error else "success",
                    elapsed_ms=result.elapsed_ms,
                    response_size=len(result.items),
                    error_message=(
                        redact_secret_text(result.error, (redfox_api_key,))
                        if result.error
                        else None
                    ),
                    error_code=type(result.error).__name__ if result.error else None,
                    cache_hit=False,
                    estimated_cost=get_settings().aihot_provider_call_cost,
                )
            )
            if result.membership.id not in current_source_ids:
                continue
            if result.error:
                source_name = (
                    result.publisher.external_id
                    if result.publisher
                    else result.membership.source_key
                )
                safe_error = redact_secret_text(result.error, (redfox_api_key,))
                errors.append(
                    f"{result.membership.platform}/{source_name}: {safe_error}"
                )
                continue

            for dto in result.items:
                if not dto.external_id:
                    continue
                item_key = (dto.platform, dto.external_id)
                was_existing = item_key in known_item_keys
                author = _xhs_author_dto(dto) if dto.platform == "xiaohongshu" else None
                if author is not None and author.external_id in xhs_publisher_errors:
                    safe_error = redact_secret_text(
                        xhs_publisher_errors[author.external_id],
                        (redfox_api_key,),
                    )
                    errors.append(f"{dto.platform}/{dto.external_id}: {safe_error}")
                    continue
                existing_item = cache.items.get(item_key)
                try:
                    async with db.begin_nested():
                        publisher_id = _publisher_id_for_item(
                            result,
                            dto,
                            xhs_publisher_ids,
                        )
                        if publisher_id is None:
                            raise ValueError("missing publisher identity")
                        item = await upsert_item(
                            db,
                            dto,
                            publisher_id,
                            existing_item=existing_item,
                            bookmarked=(
                                existing_item.id in cache.bookmarked_item_ids
                                if existing_item is not None
                                else (None if was_existing else False)
                            ),
                            flush=False,
                        )
                        metric = await record_metrics(
                            db,
                            item.id,
                            dto.metrics,
                            latest=cache.latest_metrics.get(item.id),
                            flush=False,
                        )
                except Exception as exc:  # one malformed record must not poison the batch
                    # A nested rollback expires ORM objects mutated inside the
                    # savepoint. Keeping one in the cache would trigger implicit
                    # async I/O (MissingGreenlet) on a later duplicate DTO.
                    if existing_item is not None:
                        cache.items.pop(item_key, None)
                        if existing_item in db.sync_session:
                            db.sync_session.expunge(existing_item)
                    safe_error = redact_secret_text(exc, (redfox_api_key,))
                    errors.append(
                        f"{result.membership.platform}/{dto.external_id}: {safe_error}"
                    )
                    continue
                cache.items[item_key] = item
                cache.latest_metrics[item.id] = metric
                known_item_keys.add(item_key)
                provenance_key = (item.id, result.membership.id)
                if provenance_key not in cache.provenance:
                    pending_provenance.add(provenance_key)
                total_fetched += 1
                if was_existing:
                    total_updated += 1
                else:
                    total_new += 1

        if pending_provenance:
            await db.execute(
                pg_insert(HotItemSource)
                .values(
                    [
                        {"item_id": item_id, "source_id": source_id}
                        for item_id, source_id in sorted(
                            pending_provenance,
                            key=lambda pair: (str(pair[0]), str(pair[1])),
                        )
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_hot_item_source")
            )

        successful_sources = sum(result.error is None for result in current_results)
        if not current_results:
            run.status = "empty"
        elif successful_sources == 0:
            run.status = "failed"
        elif total_fetched == 0:
            run.status = "partial" if errors else "empty"
        else:
            run.status = "partial" if errors else "success"

        # failed/empty runs never create a new snapshot, preserving last success.
        if run.status in {"success", "partial"}:
            await _compute_rankings(db, run.id, now)

        run.finished_at = datetime.now(timezone.utc)
        run.items_fetched = total_fetched
        run.items_new = total_new
        run.items_updated = total_updated
        run.error_message = "; ".join(errors)[:4000] or None
        await db.commit()
        return {
            "run_id": str(run.id),
            "status": run.status,
            "fetched": total_fetched,
            "new": total_new,
            "updated": total_updated,
            "errors": errors,
        }
    except Exception as exc:
        await db.rollback()
        safe_error = redact_secret_text(exc, (redfox_api_key,))
        failed = HotRun(
            platform="all",
            provider="redfox",
            run_type=run_type,
            status="failed",
            started_at=now,
            finished_at=datetime.now(timezone.utc),
            formula_version=FORMULA_VERSION,
            error_message=safe_error,
        )
        db.add(failed)
        await db.commit()
        # Do not attach ``exc_info`` here: traceback rendering includes the raw
        # exception message and can therefore re-expose a provider credential.
        logger.error("AIHot batch failed: %s", safe_error)
        return {"run_id": str(failed.id), "status": "failed", "error": safe_error}


async def _previous_ranks(db: AsyncSession, run_id: uuid.UUID, window: str) -> dict:
    previous_run_id = await db.scalar(
        select(HotRun.id)
        .where(
            HotRun.id != run_id,
            HotRun.platform == "all",
            HotRun.status.in_(("success", "partial")),
        )
        .order_by(desc(HotRun.finished_at))
        .limit(1)
    )
    if previous_run_id is None:
        return {}
    return dict(
        (
            await db.execute(
                select(HotRanking.item_id, HotRanking.rank).where(
                    HotRanking.run_id == previous_run_id,
                    HotRanking.window == window,
                )
            )
        ).all()
    )


async def _compute_rankings(db: AsyncSession, run_id: uuid.UUID, now: datetime) -> None:
    """Load candidates in one set query, then persist three cumulative windows."""
    latest_metric_at = (
        select(
            SocialItemMetricSnapshot.item_id,
            func.max(SocialItemMetricSnapshot.captured_at).label("captured_at"),
        )
        .group_by(SocialItemMetricSnapshot.item_id)
        .subquery()
    )
    latest_metric = aliased(SocialItemMetricSnapshot)
    enrichment = aliased(ContentEnrichment)

    rows = (
        await db.execute(
            select(SocialItem, HotSourceMembership, latest_metric, enrichment)
            .join(HotItemSource, HotItemSource.item_id == SocialItem.id)
            .join(
                HotSourceMembership,
                and_(
                    HotSourceMembership.id == HotItemSource.source_id,
                    HotSourceMembership.enabled.is_(True),
                ),
            )
            .join(
                latest_metric_at,
                latest_metric_at.c.item_id == SocialItem.id,
                isouter=True,
            )
            .join(
                latest_metric,
                and_(
                    latest_metric.item_id == latest_metric_at.c.item_id,
                    latest_metric.captured_at == latest_metric_at.c.captured_at,
                ),
                isouter=True,
            )
            .join(
                enrichment,
                and_(
                    enrichment.item_id == SocialItem.id,
                    enrichment.version == ENRICHMENT_VERSION,
                ),
                isouter=True,
            )
            .where(
                SocialItem.platform.in_(_SUPPORTED_PLATFORMS),
                SocialItem.published_at >= now - timedelta(days=7),
                # A completed negative classification is excluded. Pending AI
                # work does not block the real-metric hot list.
                (enrichment.is_financial.is_(None) | enrichment.is_financial.is_(True)),
            )
        )
    ).all()

    candidate_by_id = {}
    for item, membership, metrics, item_enrichment in rows:
        # One item can be discovered by several keywords. Rank it once and use
        # the semantic category when enrichment is available.
        candidate_by_id[item.id] = {
            "item_id": item.id,
            "platform": item.platform,
            "category": (
                item_enrichment.category
                if item_enrichment and item_enrichment.category
                else membership.category
            ),
            "published_at": item.published_at,
            "provider_rank": metrics.provider_rank if metrics else None,
            "metrics": {
                "like": metrics.like_count if metrics else 0,
                "comment": metrics.comment_count if metrics else 0,
                "share": metrics.share_count if metrics else 0,
                "collect": metrics.collect_count if metrics else 0,
                "view": metrics.view_count if metrics else 0,
                "read": (metrics.raw_metrics or {}).get("read_count", 0) if metrics else 0,
            },
        }
    candidates = list(candidate_by_id.values())

    for window in ("24h", "3d", "7d"):
        previous = await _previous_ranks(db, run_id, window)
        ranked = rank_items(candidates, window=window, previous_ranks=previous, now=now)
        for row in ranked:
            db.add(
                HotRanking(
                    run_id=run_id,
                    item_id=row["item_id"],
                    platform=row["platform"],
                    category=row["category"],
                    window=window,
                    aihot_score=row["aihot_score"],
                    rank=row["rank"],
                    previous_rank=row["previous_rank"],
                    rank_delta=row["rank_delta"],
                    platform_score=row["platform_score"],
                    freshness_score=row["freshness_score"],
                    momentum_score=row["momentum_score"],
                    formula_version=FORMULA_VERSION,
                    computed_at=now,
                )
            )
    await db.flush()

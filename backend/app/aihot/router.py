"""Public AIHot cards and administrator-only pipeline controls."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Text, and_, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.admin.deps import require_admin
from app.aihot.enrichment import ENRICHMENT_VERSION
from app.aihot.models import (
    ContentEnrichment,
    HotItemSource,
    HotRanking,
    HotRun,
    HotSourceMembership,
    ProviderCallLog,
)
from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db, get_sessionmaker
from app.core.ratelimit import _redis
from app.social.body_fetch import get_body_text
from app.social.bookmarks import ContentBookmark
from app.social.providers import get_provider
from app.social.providers.base import PublisherDTO
from app.social.providers.redfox import RedFoxProvider
from app.social.unified import upsert_publisher
from app.social.unified_models import (
    SocialItem,
    SocialItemMedia,
    SocialItemMetricSnapshot,
    SocialPublisher,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/aihot", tags=["aihot"])


class SourceCreate(BaseModel):
    publisher_id: uuid.UUID | None = None
    platform: Literal["wechat", "xiaohongshu", "bilibili"] | None = None
    external_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    avatar: str | None = Field(default=None, max_length=1024)
    description: str | None = Field(default=None, max_length=4000)
    category: Literal["macro", "policy", "industry", "company", "market"] = "market"
    source_key: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=1000)


class SourceUpdate(BaseModel):
    category: Literal["macro", "policy", "industry", "company", "market"] | None = None
    source_key: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


def _freshness(run: HotRun | None, now: datetime) -> tuple[str, float | None]:
    if run is None or run.finished_at is None:
        return "no_data", None
    age_hours = max(0.0, (now - run.finished_at).total_seconds() / 3600)
    if age_hours > 72:
        return "stale_72h", age_hours
    if age_hours > 24:
        return "stale_24h", age_hours
    return "ok", age_hours


def _trend(delta: int | None) -> str:
    if delta is None:
        return "new"
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _core_metric(platform: str, metric: SocialItemMetricSnapshot | None) -> dict | None:
    if metric is None:
        return None
    raw = metric.raw_metrics or {}
    candidates = {
        "wechat": ("阅读", raw.get("read_count") or metric.view_count),
        "xiaohongshu": ("点赞", metric.like_count),
        "bilibili": ("播放", metric.view_count),
    }
    label, value = candidates.get(platform, ("互动", metric.like_count))
    return {"label": label, "value": value} if value is not None else None


def _latest_metric_join():
    latest_at = (
        select(
            SocialItemMetricSnapshot.item_id,
            func.max(SocialItemMetricSnapshot.captured_at).label("captured_at"),
        )
        .group_by(SocialItemMetricSnapshot.item_id)
        .subquery()
    )
    metric = aliased(SocialItemMetricSnapshot)
    return latest_at, metric


async def _latest_visible_run(db: AsyncSession) -> HotRun | None:
    return (
        await db.execute(
            select(HotRun)
            .where(HotRun.platform == "all", HotRun.status.in_(("success", "partial")))
            .order_by(desc(HotRun.finished_at))
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("")
async def get_aihot(
    window: str = Query("24h", pattern="^(24h|3d|7d)$"),
    category: str | None = Query(None, pattern="^(macro|policy|industry|company|market)$"),
    q: str | None = Query(None, min_length=1, max_length=80),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one saved snapshot; provider calls never happen on a read request."""
    latest_run = await _latest_visible_run(db)
    current_time = datetime.now(timezone.utc)
    freshness, age_hours = _freshness(latest_run, current_time)
    if latest_run is None:
        return {"items": [], "run": None, "status": freshness}

    latest_at, metric = _latest_metric_join()
    enrichment = aliased(ContentEnrichment)
    bookmark = aliased(ContentBookmark)
    query = (
        select(HotRanking, SocialItem, SocialPublisher, metric, enrichment, bookmark.id)
        .join(SocialItem, HotRanking.item_id == SocialItem.id)
        .join(SocialPublisher, SocialItem.publisher_id == SocialPublisher.id)
        .join(latest_at, latest_at.c.item_id == SocialItem.id, isouter=True)
        .join(
            metric,
            and_(
                metric.item_id == latest_at.c.item_id,
                metric.captured_at == latest_at.c.captured_at,
            ),
            isouter=True,
        )
        .join(
            enrichment,
            and_(
                enrichment.item_id == SocialItem.id,
                enrichment.version == ENRICHMENT_VERSION,
                enrichment.status == "done",
            ),
            isouter=True,
        )
        .join(
            bookmark,
            and_(bookmark.item_id == SocialItem.id, bookmark.user_id == user.id),
            isouter=True,
        )
        .where(HotRanking.run_id == latest_run.id, HotRanking.window == window)
    )
    if category:
        query = query.where(func.coalesce(enrichment.category, HotRanking.category) == category)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                SocialItem.title.ilike(pattern),
                SocialItem.digest.ilike(pattern),
                SocialPublisher.name.ilike(pattern),
                enrichment.summary.ilike(pattern),
                cast(enrichment.assets, Text).ilike(pattern),
            )
        )

    rows = (await db.execute(query.order_by(HotRanking.rank).limit(limit))).all()
    items = [
        {
            "id": str(item.id),
            "rank": ranking.rank,
            "previous_rank": ranking.previous_rank,
            "rank_delta": ranking.rank_delta,
            "trend": _trend(ranking.rank_delta),
            "window": ranking.window,
            "category": enrichment_row.category if enrichment_row else ranking.category,
            "assets": enrichment_row.assets if enrichment_row else [],
            "platform": item.platform,
            "content_type": item.content_type,
            "title": item.title,
            "digest": enrichment_row.summary if enrichment_row else item.digest,
            "cover_url": item.cover_url,
            "url": item.url,
            "published_at": item.published_at.isoformat(),
            "core_metric": _core_metric(item.platform, metric_row),
            "bookmarked": bookmark_id is not None,
            "publisher": {
                "id": str(publisher.id),
                "name": publisher.name,
                "avatar": publisher.avatar,
                "platform": publisher.platform,
            },
        }
        for ranking, item, publisher, metric_row, enrichment_row, bookmark_id in rows
    ]
    is_refreshing = bool(
        await db.scalar(
            select(func.count(HotRun.id)).where(
                HotRun.status == "running",
                HotRun.started_at >= current_time - timedelta(hours=2),
            )
        )
    )
    return {
        "items": items,
        "run": {
            "id": str(latest_run.id),
            "status": latest_run.status,
            "finished_at": latest_run.finished_at.isoformat() if latest_run.finished_at else None,
            "items_fetched": latest_run.items_fetched,
            "formula_version": latest_run.formula_version,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
        },
        "status": "refreshing" if is_refreshing else freshness,
    }


@router.get("/status")
async def get_aihot_status(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    latest = await _latest_visible_run(db)
    latest_attempt = (
        await db.execute(select(HotRun).order_by(desc(HotRun.created_at)).limit(1))
    ).scalar_one_or_none()
    state, age_hours = _freshness(latest, datetime.now(timezone.utc))
    return {
        "status": state,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "last_success": _run_summary(latest),
        "last_attempt": _run_summary(latest_attempt),
    }


def _run_summary(run: HotRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "items_fetched": run.items_fetched,
        "error": run.error_message,
    }


async def _run_manual_batch() -> None:
    from app.aihot.pipeline import run_aihot_batch

    async with get_sessionmaker()() as db:
        await run_aihot_batch(db, get_settings().redfox_api_key, run_type="manual")


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_aihot(
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
):
    settings = get_settings()
    if not settings.redfox_api_key:
        raise HTTPException(503, "RedFox Provider 尚未配置")
    try:
        claimed = await _redis().set(
            "aihot:manual-refresh",
            str(admin.id),
            ex=settings.aihot_refresh_cooldown_seconds,
            nx=True,
        )
        if not claimed:
            ttl = await _redis().ttl("aihot:manual-refresh")
            raise HTTPException(429, "刷新冷却中", headers={"Retry-After": str(max(ttl, 1))})
    except HTTPException:
        raise
    except Exception as exc:  # DB lock remains the correctness boundary when Redis is down
        logger.warning("AIHot refresh cooldown unavailable; fail-open: %s", exc)
    background_tasks.add_task(_run_manual_batch)
    return {"status": "accepted"}


@router.get("/sources")
async def list_sources(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(
            select(HotSourceMembership, SocialPublisher)
            .outerjoin(SocialPublisher, HotSourceMembership.publisher_id == SocialPublisher.id)
            .order_by(
                HotSourceMembership.platform,
                func.coalesce(SocialPublisher.name, HotSourceMembership.source_key),
            )
        )
    ).all()
    return [
        {
            "id": str(membership.id),
            "publisher_id": str(publisher.id) if publisher else None,
            "platform": membership.platform,
            "external_id": publisher.external_id if publisher else None,
            "name": publisher.name if publisher else membership.source_key,
            "avatar": publisher.avatar if publisher else None,
            "category": membership.category,
            "source_key": membership.source_key,
            "enabled": membership.enabled,
            "notes": membership.notes,
        }
        for membership, publisher in rows
    ]


@router.get("/provider-stats")
async def provider_stats(
    days: int = Query(30, ge=1, le=366),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated provider health/cost; raw response payloads are never exposed."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                ProviderCallLog.provider,
                ProviderCallLog.platform,
                ProviderCallLog.operation,
                func.count(ProviderCallLog.id),
                func.count(ProviderCallLog.id).filter(ProviderCallLog.status == "failed"),
                func.avg(ProviderCallLog.elapsed_ms),
                func.coalesce(func.sum(ProviderCallLog.estimated_cost), 0),
            )
            .where(ProviderCallLog.created_at >= since)
            .group_by(
                ProviderCallLog.provider,
                ProviderCallLog.platform,
                ProviderCallLog.operation,
            )
            .order_by(ProviderCallLog.provider, ProviderCallLog.platform)
        )
    ).all()
    total_cost = sum(float(row[6]) for row in rows)
    budget = get_settings().aihot_monthly_budget
    return {
        "days": days,
        "total_estimated_cost": round(total_cost, 2),
        "budget": budget,
        "budget_warning": days >= 28 and total_cost >= budget,
        "groups": [
            {
                "provider": row[0],
                "platform": row[1],
                "operation": row[2],
                "calls": row[3],
                "errors": row[4],
                "error_rate": round(row[4] / row[3], 4) if row[3] else 0,
                "avg_elapsed_ms": round(float(row[5]), 1) if row[5] is not None else None,
                "estimated_cost": round(float(row[6]), 2),
            }
            for row in rows
        ],
    }


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def add_source(
    body: SourceCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    publisher = await db.get(SocialPublisher, body.publisher_id) if body.publisher_id else None
    if body.publisher_id and publisher is None:
        raise HTTPException(404, "发布者不存在")
    if publisher is not None and body.platform and body.platform != publisher.platform:
        raise HTTPException(422, "platform 与 publisher_id 不匹配")
    account_fields = (body.external_id, body.name, body.avatar, body.description)
    if publisher is not None and any(value is not None for value in account_fields):
        raise HTTPException(422, "publisher_id 与账号字段不能同时提交")
    if publisher is not None and body.source_key:
        raise HTTPException(422, "账号源不使用 source_key")

    platform = publisher.platform if publisher else body.platform
    if platform is None:
        raise HTTPException(422, "信源需要 platform")
    if publisher and publisher.provider != "redfox":
        raise HTTPException(422, "AIHot 首期仅支持 RedFox 信源")
    if platform == "xiaohongshu":
        if publisher is not None or any(value is not None for value in account_fields):
            raise HTTPException(422, "小红书 AIHot 仅支持关键词 source_key")
        if not body.source_key:
            raise HTTPException(422, "小红书 AIHot 需要关键词 source_key")
    elif publisher is None:
        if not body.external_id or not body.name:
            raise HTTPException(422, "公众号和 B站账号源需要 external_id 和 name")
        if body.source_key:
            raise HTTPException(422, "账号源不使用 source_key")
        publisher = await upsert_publisher(
            db,
            PublisherDTO(
                platform=platform,
                external_id=body.external_id,
                name=body.name,
                avatar=body.avatar,
                description=body.description,
                provider="redfox",
            ),
        )

    publisher_id = publisher.id if publisher is not None else None
    conditions = [
        HotSourceMembership.publisher_id == publisher_id
        if publisher
        else and_(
            HotSourceMembership.provider == "redfox",
            HotSourceMembership.platform == platform,
            HotSourceMembership.source_key == body.source_key,
        )
    ]
    existing = await db.scalar(select(HotSourceMembership).where(*conditions))
    if existing is not None:
        raise HTTPException(409, "该信源已存在")
    membership = HotSourceMembership(
        publisher_id=publisher_id,
        provider="redfox",
        platform=platform,
        category=body.category,
        source_key=body.source_key,
        added_by=admin.id,
        notes=body.notes,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return {"id": str(membership.id), "ok": True}


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    membership = await db.get(HotSourceMembership, source_id)
    if membership is None:
        raise HTTPException(404, "信源不存在")
    updates = body.model_dump(exclude_unset=True)
    if updates.get("category", ...) is None or updates.get("enabled", ...) is None:
        raise HTTPException(422, "category 和 enabled 不能为 null")
    if membership.publisher_id is not None and updates.get("source_key") is not None:
        raise HTTPException(422, "账号源不使用 source_key")
    if (
        membership.publisher_id is None
        and updates.get("source_key", membership.source_key) is None
    ):
        raise HTTPException(422, "关键词源不能清空 source_key")
    for field, value in updates.items():
        setattr(membership, field, value)
    membership.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.delete("/sources/{source_id}")
async def remove_source(
    source_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    membership = await db.get(HotSourceMembership, source_id)
    if membership is None:
        raise HTTPException(404, "信源不存在")
    await db.delete(membership)
    await db.commit()
    return {"ok": True}


@router.get("/{item_id}")
async def get_aihot_item(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    enrichment = aliased(ContentEnrichment)
    bookmark = aliased(ContentBookmark)
    row = (
        await db.execute(
            select(SocialItem, SocialPublisher, enrichment, bookmark.id)
            .join(SocialPublisher, SocialItem.publisher_id == SocialPublisher.id)
            .join(HotItemSource, HotItemSource.item_id == SocialItem.id)
            .join(
                HotSourceMembership,
                and_(
                    HotSourceMembership.id == HotItemSource.source_id,
                    HotSourceMembership.enabled.is_(True),
                ),
            )
            .join(
                enrichment,
                and_(
                    enrichment.item_id == SocialItem.id,
                    enrichment.version == ENRICHMENT_VERSION,
                ),
                isouter=True,
            )
            .join(
                bookmark,
                and_(bookmark.item_id == SocialItem.id, bookmark.user_id == user.id),
                isouter=True,
            )
            .where(SocialItem.id == item_id)
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "AIHot 内容不存在")
    item, publisher, enrichment_row, bookmark_id = row
    provider = None
    try:
        candidate = get_provider(item.platform, get_settings())
        if candidate.capabilities(item.platform).get("detail"):
            provider = candidate
        elif isinstance(candidate, RedFoxProvider):
            await candidate.aclose()
    except ValueError:
        provider = None
    try:
        await get_body_text(db, item, provider=provider)
        await db.commit()
    finally:
        if isinstance(provider, RedFoxProvider):
            await provider.aclose()
    metrics = list(
        (
            await db.execute(
                select(SocialItemMetricSnapshot)
                .where(SocialItemMetricSnapshot.item_id == item_id)
                .order_by(desc(SocialItemMetricSnapshot.captured_at))
                .limit(20)
            )
        ).scalars()
    )
    rankings = list(
        (
            await db.execute(
                select(HotRanking)
                .where(HotRanking.item_id == item_id)
                .order_by(desc(HotRanking.computed_at))
                .limit(30)
            )
        ).scalars()
    )
    media = list(
        (
            await db.execute(
                select(SocialItemMedia)
                .where(SocialItemMedia.item_id == item_id)
                .order_by(SocialItemMedia.sort_order)
            )
        ).scalars()
    )
    return {
        "id": str(item.id),
        "platform": item.platform,
        "content_type": item.content_type,
        "title": item.title,
        "digest": item.digest,
        "body_text": item.body_text,
        "transcript_text": item.transcript_text,
        "cover_url": item.cover_url,
        "url": item.url,
        "published_at": item.published_at.isoformat(),
        "bookmarked": bookmark_id is not None,
        "publisher": {
            "id": str(publisher.id),
            "name": publisher.name,
            "avatar": publisher.avatar,
            "platform": publisher.platform,
        },
        "enrichment": None
        if enrichment_row is None
        else {
            "status": enrichment_row.status,
            "summary": enrichment_row.summary,
            "category": enrichment_row.category,
            "assets": enrichment_row.assets,
            "is_financial": enrichment_row.is_financial,
            "relevance_confidence": enrichment_row.relevance_confidence,
            "model": enrichment_row.model,
            "version": enrichment_row.version,
        },
        "metrics": [
            {
                "captured_at": metric.captured_at.isoformat(),
                "view": metric.view_count,
                "like": metric.like_count,
                "comment": metric.comment_count,
                "share": metric.share_count,
                "collect": metric.collect_count,
                "provider_rank": metric.provider_rank,
            }
            for metric in metrics
        ],
        "rank_history": [
            {
                "window": ranking.window,
                "rank": ranking.rank,
                "previous_rank": ranking.previous_rank,
                "rank_delta": ranking.rank_delta,
                "platform_score": round(ranking.platform_score, 2),
                "freshness_score": round(ranking.freshness_score, 2),
                "momentum_score": round(ranking.momentum_score, 2),
                "computed_at": ranking.computed_at.isoformat(),
                "formula_version": ranking.formula_version,
            }
            for ranking in rankings
        ],
        "media": [
            {
                "type": entry.media_type,
                "url": entry.url,
                "thumbnail_url": entry.thumbnail_url,
                "duration_seconds": entry.duration_seconds,
            }
            for entry in media
        ],
    }

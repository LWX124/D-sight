"""Asynchronous financial classification and interpretation for AIHot items."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.aihot.models import ContentEnrichment, HotItemSource, HotSourceMembership
from app.core.config import get_settings
from app.social.provider_audit import redact_secret_text
from app.social.unified_models import SocialItem

logger = logging.getLogger(__name__)

ENRICHMENT_VERSION = "finance-v1"
_ENRICHMENT_LOCK_KEY = 2_024_081_012
_CATEGORIES = {"macro", "policy", "industry", "company", "market"}


class EnrichmentPayload(BaseModel):
    is_financial: bool
    relevance_confidence: float = Field(ge=0, le=1)
    summary: str = Field(max_length=280)
    category: str
    assets: list[str] = Field(default_factory=list, max_length=20)


def _fake_enrichment(item: SocialItem) -> EnrichmentPayload:
    """Deterministic local/test fallback; production never pretends this is AI."""
    content = " ".join(filter(None, (item.title, item.digest, item.body_text))).lower()
    finance_terms = ("股票", "金融", "政策", "央行", "利率", "基金", "a股", "港股", "美股")
    is_financial = any(term in content for term in finance_terms)
    category = "policy" if any(term in content for term in ("政策", "央行", "利率")) else "market"
    return EnrichmentPayload(
        is_financial=is_financial,
        relevance_confidence=0.9 if is_financial else 0.2,
        summary=(item.digest or item.title or "")[:280],
        category=category,
        assets=[],
    )


def _messages(item: SocialItem) -> list:
    content = "\n".join(
        part for part in (item.title, item.digest, item.body_text, item.transcript_text) if part
    )[:12000]
    return [
        SystemMessage(
            content=(
                "你是金融内容分类器。只依据输入内容输出结构化结果。"
                "category 必须是 macro/policy/industry/company/market 之一；"
                "assets 只写明确出现的股票、指数、基金、商品或汇率名称/代码；"
                "summary 是不超过一句话的事实摘要，不添加原文没有的信息。"
            )
        ),
        HumanMessage(content=content or "（无正文）"),
    ]


async def _invoke(item: SocialItem) -> EnrichmentPayload:
    settings = get_settings()
    if settings.fake_llm:
        return _fake_enrichment(item)
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    model = ChatDeepSeek(
        model=settings.aihot_enrichment_model,
        api_key=settings.deepseek_api_key,
        timeout=45,
        max_retries=0,
    ).with_structured_output(EnrichmentPayload)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            result = await model.ainvoke(_messages(item))
            if result.category not in _CATEGORIES:
                raise ValueError(f"unsupported category: {result.category}")
            return result
        except Exception as exc:  # each item is isolated from the rest of the batch
            last_error = exc
            if attempt < 2:
                await asyncio.sleep((1, 4)[attempt])
    assert last_error is not None
    raise last_error


async def enrich_pending_items(db: AsyncSession) -> dict[str, int | str]:
    """Process one bounded batch; admission never blocks raw-card availability."""
    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _ENRICHMENT_LOCK_KEY}
    )
    if not acquired:
        return {"status": "already_running", "processed": 0, "failed": 0}

    settings = get_settings()
    model_name = "fake" if settings.fake_llm else settings.aihot_enrichment_model
    current = aliased(ContentEnrichment)
    items = list(
        (
            await db.execute(
                select(SocialItem)
                .join(
                    current,
                    and_(
                        current.item_id == SocialItem.id,
                        current.version == ENRICHMENT_VERSION,
                    ),
                    isouter=True,
                )
                .where(
                    current.id.is_(None),
                    exists(
                        select(HotItemSource.id)
                        .join(
                            HotSourceMembership,
                            HotSourceMembership.id == HotItemSource.source_id,
                        )
                        .where(
                            HotItemSource.item_id == SocialItem.id,
                            HotSourceMembership.enabled.is_(True),
                        )
                    ),
                    SocialItem.first_seen_at
                    <= datetime.now(timezone.utc) - timedelta(seconds=30),
                )
                .order_by(SocialItem.first_seen_at)
                .limit(settings.aihot_enrichment_batch_size)
            )
        ).scalars()
    )
    if not items:
        await db.commit()
        return {"status": "empty", "processed": 0, "failed": 0}

    hashes = {item.content_hash for item in items if item.content_hash}
    cached_by_hash = {}
    if hashes:
        cached_rows = (
            await db.execute(
                select(SocialItem.content_hash, ContentEnrichment)
                .join(ContentEnrichment, ContentEnrichment.item_id == SocialItem.id)
                .where(
                    SocialItem.content_hash.in_(hashes),
                    ContentEnrichment.version == ENRICHMENT_VERSION,
                    ContentEnrichment.status == "done",
                )
            )
        ).all()
        cached_by_hash = {content_hash: result for content_hash, result in cached_rows}

    enrichments: dict = {}
    to_process: list[SocialItem] = []
    for item in items:
        cached = cached_by_hash.get(item.content_hash) if item.content_hash else None
        enrichment = ContentEnrichment(
            item_id=item.id,
            model=cached.model if cached else model_name,
            version=ENRICHMENT_VERSION,
            status="done" if cached else "processing",
        )
        if cached:
            enrichment.is_financial = cached.is_financial
            enrichment.relevance_confidence = cached.relevance_confidence
            enrichment.summary = cached.summary
            enrichment.category = cached.category
            enrichment.assets = cached.assets
            enrichment.generated_at = cached.generated_at
            item.enrichment_status = "done"
        else:
            item.enrichment_status = "processing"
            to_process.append(item)
        db.add(enrichment)
        enrichments[item.id] = enrichment
    await db.flush()

    semaphore = asyncio.Semaphore(settings.aihot_enrichment_concurrency)

    async def guarded(item: SocialItem):
        async with semaphore:
            try:
                return item.id, await _invoke(item), None
            except Exception as exc:  # noqa: BLE001
                return item.id, None, exc

    results = await asyncio.gather(*(guarded(item) for item in to_process))
    failed = 0
    item_by_id = {item.id: item for item in items}
    for item_id, payload, error in results:
        enrichment = enrichments[item_id]
        item = item_by_id[item_id]
        if error is not None:
            failed += 1
            safe_error = redact_secret_text(error, (settings.deepseek_api_key,))
            enrichment.status = "failed"
            enrichment.error = safe_error
            item.enrichment_status = "failed"
            logger.warning("AIHot enrichment failed for %s: %s", item_id, safe_error)
            continue
        enrichment.is_financial = payload.is_financial
        enrichment.relevance_confidence = payload.relevance_confidence
        enrichment.summary = payload.summary
        enrichment.category = payload.category
        enrichment.assets = payload.assets
        enrichment.status = "done"
        enrichment.generated_at = datetime.now(timezone.utc)
        item.enrichment_status = "done"

    await db.commit()
    return {"status": "partial" if failed else "success", "processed": len(items), "failed": failed}

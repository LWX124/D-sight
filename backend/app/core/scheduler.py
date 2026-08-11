import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.credits.reset import reset_all_accounts

_log = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _monthly_job():
    async with get_sessionmaker()() as s:
        n = await reset_all_accounts(s)
    _log.info("monthly credit reset done: %d accounts", n)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        _monthly_job, CronTrigger(day=1, hour=0, minute=0, timezone="Asia/Shanghai"),
        id="monthly_credit_reset", replace_existing=True,
    )

    from apscheduler.triggers.interval import IntervalTrigger
    from app.news.job import poll_all_sources

    async def _news_job():
        n = await poll_all_sources()
        _log.info("news poll done: %d new items", n)

    _scheduler.add_job(
        _news_job, IntervalTrigger(minutes=2),
        id="news_poll", replace_existing=True,
    )

    from app.core.config import get_settings
    from app.social.refresh import (
        refresh_subscribed_publishers,
        sync_legacy_weibo_publishers,
    )

    async def _social_unified_job():
        async with get_sessionmaker()() as session:
            result = await refresh_subscribed_publishers(
                session, get_settings(), include_weibo=False
            )
        _log.info("unified social poll done: %s", result)

    _scheduler.add_job(
        _social_unified_job,
        IntervalTrigger(minutes=get_settings().social_unified_poll_minutes),
        id="social_unified_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Weibo keeps its credential-aware, rate-limit-aware polling round. Once
    # that safe collector finishes, mirror the immutable snapshots into the
    # unified read model without making a second upstream request.
    from app.social.weibo.job import poll_all_subscriptions as poll_all_weibo

    async def _weibo_job():
        async with get_sessionmaker()() as session:
            acquired = await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": 2_024_081_014},
            )
            if not acquired:
                _log.info("weibo poll skipped: another process owns the round")
                return
            added = await poll_all_weibo()
            projected = await sync_legacy_weibo_publishers(session, get_settings())
            await session.commit()
        _log.info("weibo poll done: %d new posts; unified=%s", added, projected)

    _scheduler.add_job(
        _weibo_job,
        IntervalTrigger(minutes=get_settings().weibo_poll_minutes),
        id="weibo_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    from app.aihot.cleanup import cleanup_expired_content
    from app.aihot.enrichment import enrich_pending_items
    from app.aihot.pipeline import run_aihot_batch

    async def _aihot_job():
        settings = get_settings()
        if not settings.redfox_api_key:
            _log.warning("AIHot poll skipped: REDFOX_API_KEY is not configured")
            return
        async with get_sessionmaker()() as session:
            result = await run_aihot_batch(
                session, settings.redfox_api_key, run_type="scheduled"
            )
        _log.info("AIHot poll done: %s", result)

    async def _aihot_enrichment_job():
        async with get_sessionmaker()() as session:
            result = await enrich_pending_items(session)
        if result["status"] not in {"empty", "already_running"}:
            _log.info("AIHot enrichment done: %s", result)

    async def _social_cleanup_job():
        async with get_sessionmaker()() as session:
            result = await cleanup_expired_content(session)
        _log.info("social retention cleanup done: %s", result)

    _scheduler.add_job(
        _aihot_job,
        IntervalTrigger(minutes=get_settings().aihot_poll_minutes),
        id="aihot_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _aihot_enrichment_job,
        IntervalTrigger(minutes=1),
        id="aihot_enrichment",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _social_cleanup_job,
        CronTrigger(hour=3, minute=15, timezone="Asia/Shanghai"),
        id="social_retention_cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    from app.fund_arb.job import evening_pipeline, morning_job, snapshot_tick

    async def _fund_arb_tick():
        n = await snapshot_tick()
        if n:
            _log.debug("fund_arb snapshot: %d funds", n)

    _scheduler.add_job(
        _fund_arb_tick,
        IntervalTrigger(seconds=get_settings().fund_arb_snapshot_seconds),
        id="fund_arb_snapshot", replace_existing=True, max_instances=1, coalesce=True,
    )
    _scheduler.add_job(
        evening_pipeline, CronTrigger(hour="18,20", minute=0, timezone="Asia/Shanghai"),
        id="fund_arb_evening", replace_existing=True,
    )
    _scheduler.add_job(
        evening_pipeline, CronTrigger(hour=21, minute=30, timezone="Asia/Shanghai"),
        id="fund_arb_evening_late", replace_existing=True,
    )
    _scheduler.add_job(
        morning_job, CronTrigger(hour=9, minute=20, timezone="Asia/Shanghai"),
        id="fund_arb_morning", replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

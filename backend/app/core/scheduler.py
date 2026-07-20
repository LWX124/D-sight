import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
    from app.social.job import poll_all_subscriptions

    async def _social_job():
        n = await poll_all_subscriptions()
        _log.info("social poll done: %d new articles", n)

    _scheduler.add_job(
        _social_job, IntervalTrigger(minutes=get_settings().social_poll_minutes),
        id="social_poll", replace_existing=True,
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

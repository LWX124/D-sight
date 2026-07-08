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
        _news_job, IntervalTrigger(minutes=5),
        id="news_poll", replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

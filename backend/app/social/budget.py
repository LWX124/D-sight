"""Database-enforced provider request budgets.

The reservation commits before the network request, so failures and caller
rollbacks never refund a token. Redis is deliberately not part of this safety
boundary.
"""

from __future__ import annotations

import uuid
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.social.unified_models import SocialProviderDailyUsage

logger = logging.getLogger(__name__)


class ProviderBudgetExceeded(Exception):
    def __init__(self, provider: str, retry_at: datetime) -> None:
        super().__init__(f"{provider} daily request budget exhausted")
        self.provider = provider
        self.retry_at = retry_at
        self.code = "daily_budget_exhausted"


def _next_utc_day(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)


async def consume_daily_request(
    db: AsyncSession,
    provider: str,
    limit: int,
    *,
    usage_date: date | None = None,
    commit: bool = True,
) -> int:
    """Atomically reserve one request and return the remaining daily capacity."""

    day = usage_date or datetime.now(timezone.utc).date()
    if limit <= 0:
        raise ProviderBudgetExceeded(provider, _next_utc_day(day))
    statement = (
        pg_insert(SocialProviderDailyUsage)
        .values(
            id=uuid.uuid4(),
            provider=provider,
            usage_date=day,
            request_count=1,
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="uq_social_provider_daily_usage",
            set_={
                "request_count": SocialProviderDailyUsage.request_count + 1,
                "updated_at": datetime.now(timezone.utc),
            },
            where=SocialProviderDailyUsage.request_count < limit,
        )
        .returning(SocialProviderDailyUsage.request_count)
    )
    count = (await db.execute(statement)).scalar_one_or_none()
    if count is None:
        if commit:
            await db.commit()
        raise ProviderBudgetExceeded(provider, _next_utc_day(day))
    if commit:
        await db.commit()
    remaining = max(0, limit - count)
    logger.info(
        "social provider budget reserved provider=%s date=%s used=%d remaining=%d",
        provider,
        day,
        count,
        remaining,
    )
    return remaining


async def reserve_wechat_request() -> int:
    """Reserve independently so a failed upstream call still consumes budget."""

    from app.core.config import get_settings

    settings = get_settings()
    async with get_sessionmaker()() as db:
        return await consume_daily_request(
            db,
            "wechat_mp",
            settings.social_wechat_daily_request_budget,
        )


async def get_daily_usage(
    db: AsyncSession, provider: str, usage_date: date | None = None
) -> int:
    day = usage_date or datetime.now(timezone.utc).date()
    count = await db.scalar(
        select(SocialProviderDailyUsage.request_count).where(
            SocialProviderDailyUsage.provider == provider,
            SocialProviderDailyUsage.usage_date == day,
        )
    )
    return int(count or 0)

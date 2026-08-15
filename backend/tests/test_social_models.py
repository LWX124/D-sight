import datetime as dt
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.auth.models import User  # noqa: F401  # register users table for FK resolution
from app.social.models import (
    WechatAccount,
    WechatArticle,
    WechatCredential,
)
from app.social.budget import ProviderBudgetExceeded, consume_daily_request
from app.social.unified_models import SocialProviderDailyUsage


@pytest.mark.asyncio
async def test_create_account_article_credential(db_session):
    acc = WechatAccount(fakeid="fake1", name="某公众号")
    db_session.add(acc)
    await db_session.flush()

    art = WechatArticle(
        account_id=acc.id, external_id="aid1", title="标题", url="https://mp/s/x",
        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
    )
    db_session.add(art)

    cred = WechatCredential(
        user_id=None, token="enc-t", cookies="enc-c", nickname="我的号",
        expires_at=dt.datetime(2026, 7, 14, tzinfo=dt.UTC), status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    assert art.content is None  # 懒抓，初始空
    assert cred.status == "active"


@pytest.mark.asyncio
async def test_provider_daily_budget_is_atomic_under_concurrency():
    from app.core.db import get_sessionmaker

    provider = f"budget-{uuid.uuid4().hex[:20]}"

    async def reserve() -> bool:
        async with get_sessionmaker()() as db:
            try:
                await consume_daily_request(db, provider, 50)
            except ProviderBudgetExceeded:
                return False
            return True

    results = await asyncio.gather(*(reserve() for _ in range(60)))
    assert sum(results) == 50
    async with get_sessionmaker()() as db:
        row = await db.scalar(
            select(SocialProviderDailyUsage).where(
                SocialProviderDailyUsage.provider == provider
            )
        )
        assert row.request_count == 50


@pytest.mark.asyncio
async def test_provider_daily_budget_resets_by_date_and_survives_rollback(db_session):
    provider = f"budget-date-{uuid.uuid4().hex[:16]}"
    first_day = dt.date(2026, 8, 14)
    assert await consume_daily_request(
        db_session, provider, 1, usage_date=first_day
    ) == 0
    await db_session.rollback()
    with pytest.raises(ProviderBudgetExceeded):
        await consume_daily_request(db_session, provider, 1, usage_date=first_day)
    assert await consume_daily_request(
        db_session, provider, 1, usage_date=first_day + dt.timedelta(days=1)
    ) == 0

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import delete

from app.auth.models import User
from app.core.security import hash_password
from app.social.models import WeiboAccount, WeiboSubscription
from app.social.weibo.credentials import ActiveWeiboCredential
from app.social.weibo.errors import WeiboRateLimitedError, WeiboTransientError


async def _clear_weibo_subscriptions(db_session):
    """Isolate global-poll tests in the suite's shared PostgreSQL container."""
    await db_session.execute(delete(WeiboSubscription))
    await db_session.commit()


@pytest.mark.asyncio
async def test_job_makes_no_request_during_global_cooldown(monkeypatch):
    from app.social.weibo import job

    async def cooling():
        return 60

    monkeypatch.setattr(job.cooldown, "remaining", cooling)
    monkeypatch.setattr(
        job,
        "get_sessionmaker",
        lambda: (_ for _ in ()).throw(AssertionError("cooldown must short-circuit DB and HTTP")),
    )
    assert await job.poll_all_subscriptions() == 0


@pytest.mark.asyncio
async def test_job_isolates_transient_account_error(db_session, monkeypatch):
    from app.social.weibo import job

    await _clear_weibo_subscriptions(db_session)
    user = User(email=f"weibo-job-{uuid.uuid4().hex}@t.dev", password_hash=hash_password("x"))
    accounts = [
        WeiboAccount(
            uid=f"6{uuid.uuid4().int % 10**10:010d}",
            name=f"账号{index}",
            profile_url="https://weibo.com/u/6",
            container_id=f"1076036{index}",
        )
        for index in range(2)
    ]
    db_session.add_all([user, *accounts])
    await db_session.flush()
    db_session.add_all(
        [WeiboSubscription(user_id=user.id, account_id=row.id, enabled=True) for row in accounts]
    )
    await db_session.commit()

    async def no_cooldown():
        return 0

    async def credential(db):
        return ActiveWeiboCredential(uuid.uuid4(), "test=1")

    @asynccontextmanager
    async def client(cookies):
        yield object()

    calls = []

    async def ingest(db, account, credential, upstream):
        calls.append(account.id)
        if len(calls) == 1:
            raise WeiboTransientError("temporary")
        return 1

    monkeypatch.setattr(job.cooldown, "remaining", no_cooldown)
    monkeypatch.setattr(job, "pick_credential", credential)
    monkeypatch.setattr(job, "new_weibo_client", client)
    monkeypatch.setattr(job, "ingest_account", ingest)
    monkeypatch.setattr(job, "_gap", no_cooldown)
    assert await job.poll_all_subscriptions() == 1
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_job_stops_entire_round_on_rate_limit(db_session, monkeypatch):
    from app.social.weibo import job

    await _clear_weibo_subscriptions(db_session)
    user = User(email=f"weibo-rate-{uuid.uuid4().hex}@t.dev", password_hash=hash_password("x"))
    accounts = [
        WeiboAccount(
            uid=f"5{uuid.uuid4().int % 10**10:010d}",
            name=f"风控账号{index}",
            profile_url="https://weibo.com/u/5",
            container_id=f"1076035{index}",
        )
        for index in range(2)
    ]
    db_session.add_all([user, *accounts])
    await db_session.flush()
    db_session.add_all(
        [WeiboSubscription(user_id=user.id, account_id=row.id, enabled=True) for row in accounts]
    )
    await db_session.commit()

    async def no_cooldown():
        return 0

    async def credential(db):
        return ActiveWeiboCredential(uuid.uuid4(), "test=1")

    @asynccontextmanager
    async def client(cookies):
        yield object()

    calls = 0

    async def ingest(db, account, credential, upstream):
        nonlocal calls
        calls += 1
        raise WeiboRateLimitedError("HTTP 432")

    async def ignore(*args):
        return None

    monkeypatch.setattr(job.cooldown, "remaining", no_cooldown)
    monkeypatch.setattr(job.cooldown, "trip", ignore)
    monkeypatch.setattr(job, "pick_credential", credential)
    monkeypatch.setattr(job, "new_weibo_client", client)
    monkeypatch.setattr(job, "ingest_account", ingest)
    monkeypatch.setattr(job, "mark_blocked", ignore)
    assert await job.poll_all_subscriptions() == 0
    assert calls == 1

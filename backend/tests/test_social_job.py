import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.social.models import WechatArticle


def _appmsg_handler(aids):
    appmsgex = [{"aid": a, "title": f"T{a}", "digest": "", "cover": "",
                 "link": f"https://mp/s/{a}", "create_time": 1751000000} for a in aids]
    page = json.dumps({"publish_list": [{"publish_info": json.dumps({"appmsgex": appmsgex})}], "total_count": len(aids)})
    return lambda request: httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": page})


@pytest.mark.asyncio
async def test_poll_inserts_for_enabled_subs(db_session, monkeypatch):
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatSubscription
    from app.social.wechat.client import ActiveCred

    u = User(email=f"job-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    db_session.add(WechatSubscription(user_id=u.id, account_id=acc.id, enabled=True, interval_seconds=1800))
    await db_session.commit()

    aids = [f"j{uuid.uuid4().hex[:6]}", f"j{uuid.uuid4().hex[:6]}"]

    async def fake_pick(db):
        return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")
    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(job, "new_mp_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids))))

    added = await job.poll_all_subscriptions()
    assert added >= 2
    n = await db_session.scalar(select(func.count()).select_from(WechatArticle).where(WechatArticle.account_id == acc.id))
    assert n == 2


@pytest.mark.asyncio
async def test_poll_skips_when_pool_empty(db_session, monkeypatch):
    from app.social import job

    async def fake_pick(db):
        return None
    monkeypatch.setattr(job, "pick_credential", fake_pick)
    added = await job.poll_all_subscriptions()
    assert added == 0

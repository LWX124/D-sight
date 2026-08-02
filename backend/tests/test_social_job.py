import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select, update

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
async def test_ingest_text_post_long_title(db_session):
    # 公众号「文字消息」无标题，接口把全文塞进 title，可远超 512 字符
    from app.social.ingest import get_or_create_account, ingest_account
    from app.social.wechat.client import ActiveCred

    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    aid = f"t{uuid.uuid4().hex[:6]}"
    long_title = "创业板指已在跌破趋势的边缘" * 100
    appmsgex = [{"aid": aid, "title": long_title, "digest": "", "cover": "",
                 "link": f"https://mp/s/{aid}", "create_time": 1751000000}]
    page = json.dumps({"publish_list": [{"publish_info": json.dumps({"appmsgex": appmsgex})}]})
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": page})))

    added = await ingest_account(db_session, acc, ActiveCred(id=uuid.uuid4(), token="t", cookies="c"), http)
    assert len(added) == 1
    art = await db_session.scalar(select(WechatArticle).where(WechatArticle.account_id == acc.id))
    assert art.title == long_title


@pytest.mark.asyncio
async def test_poll_skips_when_pool_empty(db_session, monkeypatch):
    from app.social import job

    async def fake_pick(db):
        return None
    monkeypatch.setattr(job, "pick_credential", fake_pick)
    added = await job.poll_all_subscriptions()
    assert added == 0


@pytest.mark.asyncio
async def test_ingest_account_returns_new_article_ids(db_session):
    """返回 id 列表而非计数：KB 增量钩子需要知道哪些是新增的。"""
    from app.social.ingest import get_or_create_account, ingest_account
    from app.social.wechat.client import ActiveCred

    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    aids = [f"r{uuid.uuid4().hex[:6]}", f"r{uuid.uuid4().hex[:6]}"]
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids)))

    ids = await ingest_account(db_session, acc, ActiveCred(id=uuid.uuid4(), token="t", cookies="c"), http)
    assert isinstance(ids, list) and len(ids) == 2
    rows = (await db_session.execute(
        select(WechatArticle.id).where(WechatArticle.account_id == acc.id)
    )).scalars().all()
    assert set(ids) == set(rows)

    # 第二次同样的 aid → 无新增
    http2 = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids)))
    assert await ingest_account(db_session, acc, ActiveCred(id=uuid.uuid4(), token="t", cookies="c"), http2) == []


@pytest.mark.asyncio
async def test_poll_calls_kb_hook_with_new_ids(db_session, monkeypatch):
    """poll 拿到新增 id 后调 KB 钩子；计数语义不变（仍返回新增文章数）。"""
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatSubscription
    from app.social.wechat.client import ActiveCred

    # 清掉前序用例残留的 enabled 订阅（DB 跨用例不回滚），避免污染本用例计数
    await db_session.execute(update(WechatSubscription).values(enabled=False))
    await db_session.commit()

    u = User(email=f"hook-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    db_session.add(WechatSubscription(user_id=u.id, account_id=acc.id, enabled=True))
    await db_session.commit()

    aids = [f"h{uuid.uuid4().hex[:6]}"]
    seen = []

    async def fake_hook(account_id, article_ids):
        seen.append((account_id, list(article_ids)))
        return 0

    async def fake_pick(db):
        return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")

    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(job, "new_mp_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(aids))))
    monkeypatch.setattr(job, "ingest_new_articles_for_account", fake_hook)

    added = await job.poll_all_subscriptions()
    assert added == 1                       # 计数语义保持不变
    assert len(seen) == 1 and seen[0][0] == acc.id and len(seen[0][1]) == 1


@pytest.mark.asyncio
async def test_poll_survives_kb_hook_failure(db_session, monkeypatch):
    """KB 入库出问题不该让社媒 poll 整轮失败——两者是独立关注点。"""
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatSubscription
    from app.social.wechat.client import ActiveCred

    # 清掉前序用例残留的 enabled 订阅（DB 跨用例不回滚），避免污染本用例计数
    await db_session.execute(update(WechatSubscription).values(enabled=False))
    await db_session.commit()

    u = User(email=f"hookf-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    db_session.add(WechatSubscription(user_id=u.id, account_id=acc.id, enabled=True))
    await db_session.commit()

    async def boom(account_id, article_ids):
        raise RuntimeError("kb 挂了")

    async def fake_pick(db):
        return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")

    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(job, "new_mp_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_appmsg_handler([f"k{uuid.uuid4().hex[:6]}"]))))
    monkeypatch.setattr(job, "ingest_new_articles_for_account", boom)

    assert await job.poll_all_subscriptions() == 1   # 不抛，计数照常

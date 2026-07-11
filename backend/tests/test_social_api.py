import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.core.security import create_access_token
from app.social import crypto
from app.social.models import WechatAccount, WechatArticle, WechatCredential, WechatSubscription
from app.social.wechat.errors import SessionExpiredError


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.mark.asyncio
async def test_requires_auth(client):
    r = await client.get("/api/social/wechat/subscriptions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_subscribe_idempotent_and_list(client, db_session, registered_user):
    h = _auth(registered_user)
    body = {"fakeid": f"F{uuid.uuid4().hex[:6]}", "name": "投研号", "avatar": None}
    r1 = await client.post("/api/social/wechat/subscriptions", json=body, headers=h)
    assert r1.status_code == 200
    r2 = await client.post("/api/social/wechat/subscriptions", json=body, headers=h)
    assert r2.status_code == 200  # 幂等，不 500
    subs = (await client.get("/api/social/wechat/subscriptions", headers=h)).json()
    assert any(s["name"] == "投研号" for s in subs)
    n = await db_session.scalar(
        select(func.count()).select_from(WechatAccount).where(WechatAccount.fakeid == body["fakeid"])
    )
    assert n == 1


@pytest.mark.asyncio
async def test_list_articles(client, db_session, registered_user):
    h = _auth(registered_user)
    acc = WechatAccount(fakeid=f"A{uuid.uuid4().hex[:6]}", name="号X")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(WechatArticle(
        account_id=acc.id, external_id="e1", title="标题X", url="https://mp/s/e1",
        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
    ))
    await db_session.commit()
    arts = (await client.get(f"/api/social/wechat/articles?account_id={acc.id}", headers=h)).json()
    assert arts[0]["title"] == "标题X"
    assert arts[0]["content"] is None


@pytest.mark.asyncio
async def test_article_lazy_fetch(client, db_session, registered_user, monkeypatch):
    h = _auth(registered_user)
    acc = WechatAccount(fakeid=f"B{uuid.uuid4().hex[:6]}", name="号Y")
    db_session.add(acc)
    await db_session.flush()
    art = WechatArticle(account_id=acc.id, external_id="e2", title="待抓", url="https://mp/s/e2",
                        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC))
    db_session.add(art)
    await db_session.commit()

    import app.social.router as router_mod

    async def fake_fetch(db, article, http):
        article.content = "抓到的正文"
        article.content_fetched_at = dt.datetime.now(dt.UTC)
        await db.commit()
        return "抓到的正文"
    monkeypatch.setattr(router_mod, "fetch_article_content", fake_fetch)

    got = (await client.get(f"/api/social/wechat/articles/{art.id}", headers=h)).json()
    assert got["content"] == "抓到的正文"


@pytest.mark.asyncio
async def test_get_article_refetches_empty_content(client, db_session, registered_user, monkeypatch):
    h = _auth(registered_user)
    acc = WechatAccount(fakeid=f"C{uuid.uuid4().hex[:6]}", name="号E")
    db_session.add(acc)
    await db_session.flush()
    art = WechatArticle(account_id=acc.id, external_id="e3", title="空正文", url="https://mp/s/e3",
                        content="", published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC))
    db_session.add(art)
    await db_session.commit()

    import app.social.router as router_mod

    async def fake_fetch(db, article, http):
        article.content = "补抓正文"
        article.content_fetched_at = dt.datetime.now(dt.UTC)
        await db.commit()
        return "补抓正文"
    monkeypatch.setattr(router_mod, "fetch_article_content", fake_fetch)

    got = (await client.get(f"/api/social/wechat/articles/{art.id}", headers=h)).json()
    assert got["content"] == "补抓正文"


@pytest.mark.asyncio
async def test_get_article_fetch_failure_returns_503(client, db_session, registered_user, monkeypatch):
    h = _auth(registered_user)
    acc = WechatAccount(fakeid=f"D{uuid.uuid4().hex[:6]}", name="号F")
    db_session.add(acc)
    await db_session.flush()
    art = WechatArticle(account_id=acc.id, external_id="e4", title="抓取失败", url="https://mp/s/e4",
                        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC))
    db_session.add(art)
    await db_session.commit()

    import app.social.router as router_mod

    async def fake_fetch(db, article, http):
        raise RuntimeError("boom")
    monkeypatch.setattr(router_mod, "fetch_article_content", fake_fetch)

    r = await client.get(f"/api/social/wechat/articles/{art.id}", headers=h)
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_search_session_expired_marks_credential(client, db_session, registered_user, monkeypatch):
    h = _auth(registered_user)
    cred = WechatCredential(
        token=crypto.encrypt("t"), cookies=crypto.encrypt("c"), nickname="号Z",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1), status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    import app.social.router as router_mod

    async def fake_search_biz(http, cred, keyword):
        raise SessionExpiredError("200003:会话失效")
    monkeypatch.setattr(router_mod, "search_biz", fake_search_biz)

    r = await client.get("/api/social/wechat/search?keyword=x", headers=h)
    assert r.status_code == 409

    await db_session.refresh(cred)
    assert cred.status == "expired"

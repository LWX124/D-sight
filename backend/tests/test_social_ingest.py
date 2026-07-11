import datetime as dt
import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.auth.models import User  # noqa: F401 — 注册 FK 目标表
from app.social.models import WechatAccount, WechatArticle
from app.social.wechat.client import ActiveCred


def _cred():
    return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")


def _appmsg_handler(aids):
    appmsgex = [{"aid": a, "title": f"T{a}", "digest": "d", "cover": "",
                 "link": f"https://mp/s/{a}", "create_time": 1751000000} for a in aids]
    page = json.dumps({"publish_list": [{"publish_info": json.dumps({"appmsgex": appmsgex})}],
                       "total_count": len(aids)})

    def handler(request):
        if "appmsgpublish" in str(request.url):
            return httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": page})
        return httpx.Response(200, text='<div id="js_content"><p>正文内容。</p></div>')
    return handler


@pytest.mark.asyncio
async def test_get_or_create_account_idempotent(db_session):
    from app.social.ingest import get_or_create_account

    fid = f"FID{uuid.uuid4().hex[:6]}"
    a1 = await get_or_create_account(db_session, fid, "号名")
    a2 = await get_or_create_account(db_session, fid, "号名改")
    assert a1.id == a2.id
    n = await db_session.scalar(select(func.count()).select_from(WechatAccount).where(WechatAccount.fakeid == fid))
    assert n == 1


@pytest.mark.asyncio
async def test_ingest_dedup(db_session):
    from app.social.ingest import get_or_create_account, ingest_account

    acc = await get_or_create_account(db_session, f"FID{uuid.uuid4().hex[:6]}", "号2")
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(["x1", "x2"])))
    async with http:
        added1 = await ingest_account(db_session, acc, _cred(), http)
        added2 = await ingest_account(db_session, acc, _cred(), http)  # 同样两篇
    assert added1 == 2
    assert added2 == 0
    total = await db_session.scalar(
        select(func.count()).select_from(WechatArticle).where(WechatArticle.account_id == acc.id)
    )
    assert total == 2


@pytest.mark.asyncio
async def test_lazy_fetch_content(db_session):
    from app.social.ingest import fetch_article_content, get_or_create_account, ingest_account

    acc = await get_or_create_account(db_session, f"FID{uuid.uuid4().hex[:6]}", "号3")
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(["y1"])))
    async with http:
        await ingest_account(db_session, acc, _cred(), http)
        art = await db_session.scalar(select(WechatArticle).where(WechatArticle.account_id == acc.id))
        assert art.content is None
        text = await fetch_article_content(db_session, art, http)
    assert "正文内容。" in text
    assert art.content is not None
    assert art.content_fetched_at is not None


@pytest.mark.asyncio
async def test_lazy_fetch_retries_empty_content(db_session):
    from app.social.ingest import fetch_article_content, get_or_create_account, ingest_account

    acc = await get_or_create_account(db_session, f"FID{uuid.uuid4().hex[:6]}", "号4")
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(["z1"])))
    async with http:
        await ingest_account(db_session, acc, _cred(), http)
        art = await db_session.scalar(select(WechatArticle).where(WechatArticle.account_id == acc.id))
        art.content = ""  # 之前抓到的是空字符串，不应被当成"已抓取"永久缓存
        await db_session.commit()
        text = await fetch_article_content(db_session, art, http)
    assert "正文内容。" in text
    assert art.content == text

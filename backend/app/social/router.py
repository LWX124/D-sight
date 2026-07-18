import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.social.credentials import mark_expired, pick_credential
from app.social.ingest import fetch_article_content, get_or_create_account
from app.social.models import (
    WechatAccount,
    WechatArticle,
    WechatCredential,
    WechatSubscription,
)
from app.social.schemas import (
    AccountOut,
    ArticleOut,
    CredentialOut,
    SubscribeIn,
    SubscriptionOut,
)
from app.social.wechat.client import new_mp_client, search_biz
from app.social.wechat.errors import SessionExpiredError, TransientMpError
from app.social.wechat.login import poll_status, start_qrcode

router = APIRouter(prefix="/api/social", tags=["social"])


# ---- 登录 ----
@router.post("/wechat/login/qrcode")
async def login_qrcode(user: User = Depends(get_current_user)) -> dict:
    import base64

    try:
        session_id, mime, img = await start_qrcode()
    except TransientMpError:
        raise HTTPException(503, "微信接口暂时不可用（限流），请稍后重试")
    return {"login_session": session_id,
            "qrcode": f"data:{mime};base64," + base64.b64encode(img).decode()}


@router.get("/wechat/login/status")
async def login_status(
    s: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await poll_status(db, s, user.id)


@router.get("/wechat/credentials", response_model=list[CredentialOut])
async def my_credentials(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(WechatCredential).where(WechatCredential.user_id == user.id)
    )).scalars().all()
    return [
        CredentialOut(id=str(c.id), nickname=c.nickname, avatar=c.avatar, status=c.status,
                      expires_at=c.expires_at.isoformat())
        for c in rows
    ]


@router.delete("/wechat/credentials/{cred_id}")
async def delete_credential(
    cred_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    c = await db.get(WechatCredential, cred_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "凭证不存在")
    await db.delete(c)
    await db.commit()
    return {"ok": True}


# ---- 搜索 / 订阅 ----
@router.get("/wechat/search")
async def search(
    keyword: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    cred = await pick_credential(db)
    if cred is None:
        raise HTTPException(409, "凭证池为空，请先扫码登录一个公众号")
    try:
        async with new_mp_client() as http:
            return await search_biz(http, cred, keyword)
    except SessionExpiredError:
        await mark_expired(db, cred.id)
        raise HTTPException(409, "凭证已失效，请重新扫码登录")
    except TransientMpError:
        raise HTTPException(503, "微信接口暂时不可用（限流），请稍后重试")


@router.post("/wechat/subscriptions", response_model=SubscriptionOut)
async def subscribe(
    body: SubscribeIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    acc = await get_or_create_account(db, body.fakeid, body.name, body.avatar)
    sub = await db.scalar(
        select(WechatSubscription).where(
            WechatSubscription.user_id == user.id, WechatSubscription.account_id == acc.id
        )
    )
    if sub is None:
        sub = WechatSubscription(user_id=user.id, account_id=acc.id, enabled=True)
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
    return SubscriptionOut(id=str(sub.id), account_id=str(acc.id), fakeid=acc.fakeid,
                           name=acc.name, avatar=acc.avatar, enabled=sub.enabled)


@router.get("/wechat/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(WechatSubscription, WechatAccount)
        .join(WechatAccount, WechatSubscription.account_id == WechatAccount.id)
        .where(WechatSubscription.user_id == user.id)
    )).all()
    return [
        SubscriptionOut(id=str(sub.id), account_id=str(acc.id), fakeid=acc.fakeid,
                        name=acc.name, avatar=acc.avatar, enabled=sub.enabled)
        for sub, acc in rows
    ]


@router.delete("/wechat/subscriptions/{sub_id}")
async def unsubscribe(
    sub_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    sub = await db.get(WechatSubscription, sub_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    await db.delete(sub)
    await db.commit()
    return {"ok": True}


# ---- 文章 ----
@router.get("/wechat/articles", response_model=list[ArticleOut])
async def list_articles(
    account_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    before: dt.datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(WechatArticle).where(WechatArticle.account_id == account_id)
    if before is not None:
        q = q.where(WechatArticle.published_at < before)
    q = q.order_by(WechatArticle.published_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [_article_out(r) for r in rows]


@router.get("/wechat/articles/{article_id}", response_model=ArticleOut)
async def get_article(
    article_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    art = await db.get(WechatArticle, article_id)
    if art is None:
        raise HTTPException(404, "文章不存在")
    if not art.content:
        try:
            async with new_mp_client() as http:
                await fetch_article_content(db, art, http)
        except Exception as e:  # noqa: BLE001 — 正文抓取失败优雅降级
            raise HTTPException(503, "文章正文暂时获取失败，请稍后重试") from e
    return _article_out(art)


@router.post("/wechat/refresh")
async def refresh(
    account_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.social.ingest import ingest_account

    cred = await pick_credential(db)
    if cred is None:
        raise HTTPException(409, "凭证池为空，请先扫码登录一个公众号")
    acc = await db.get(WechatAccount, account_id)
    if acc is None:
        raise HTTPException(404, "公众号不存在")
    try:
        async with new_mp_client() as http:
            added = await ingest_account(db, acc, cred, http)
    except SessionExpiredError:
        await mark_expired(db, cred.id)
        raise HTTPException(409, "凭证已失效，请重新扫码登录")
    except TransientMpError:
        raise HTTPException(503, "微信接口暂时不可用（限流），请稍后重试")
    return {"added": added}


def _article_out(r: WechatArticle) -> ArticleOut:
    return ArticleOut(
        id=str(r.id), account_id=str(r.account_id), title=r.title, digest=r.digest,
        cover_url=r.cover_url, url=r.url, content=r.content, published_at=r.published_at.isoformat(),
    )

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.models import WechatAccount, WechatArticle
from app.social.wechat.client import ActiveCred, appmsg_publish, fetch_article_text


async def get_or_create_account(
    db: AsyncSession, fakeid: str, name: str, avatar: str | None = None, signature: str | None = None
) -> WechatAccount:
    acc = await db.scalar(select(WechatAccount).where(WechatAccount.fakeid == fakeid))
    if acc is not None:
        return acc
    acc = WechatAccount(fakeid=fakeid, name=name, avatar=avatar, signature=signature)
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    return acc


async def ingest_account(db: AsyncSession, account: WechatAccount, cred: ActiveCred, http, count: int = 20) -> int:
    from app.core.config import get_settings

    n = count or get_settings().social_fetch_count
    raws = await appmsg_publish(http, cred, account.fakeid, begin=0, count=n)
    added = 0
    for raw in raws:
        exists = await db.scalar(
            select(WechatArticle.id).where(
                WechatArticle.account_id == account.id, WechatArticle.external_id == raw.external_id
            )
        )
        if exists is not None:
            continue
        db.add(WechatArticle(
            account_id=account.id, external_id=raw.external_id, title=raw.title,
            digest=raw.digest, cover_url=raw.cover_url, url=raw.url, published_at=raw.published_at,
        ))
        added += 1
    await db.commit()
    return added


async def fetch_article_content(db: AsyncSession, article: WechatArticle, http) -> str:
    if article.content:
        return article.content
    text = await fetch_article_text(http, article.url)
    article.content = text
    article.content_fetched_at = dt.datetime.now(dt.UTC)
    await db.commit()
    return text

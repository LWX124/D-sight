import datetime as dt
import uuid

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


async def ingest_account(
    db: AsyncSession, account: WechatAccount, cred: ActiveCred, http, count: int = 20
) -> list[uuid.UUID]:
    """增量抓取该号文章，返回本轮新增文章的 id 列表。

    返回 id 而非计数：KB 整号订阅的增量钩子需要知道具体是哪几篇。调用方要计数
    直接 len()。
    """
    from app.core.config import get_settings

    n = count or get_settings().social_fetch_count
    raws = await appmsg_publish(http, cred, account.fakeid, begin=0, count=n)
    new_ids: list[uuid.UUID] = []
    for raw in raws:
        exists = await db.scalar(
            select(WechatArticle.id).where(
                WechatArticle.account_id == account.id, WechatArticle.external_id == raw.external_id
            )
        )
        if exists is not None:
            continue
        art = WechatArticle(
            account_id=account.id, external_id=raw.external_id, title=raw.title,
            digest=raw.digest, cover_url=raw.cover_url, url=raw.url, published_at=raw.published_at,
        )
        db.add(art)
        await db.flush()          # 拿到自动生成的 id
        new_ids.append(art.id)
    await db.commit()
    return new_ids


async def fetch_article_content(db: AsyncSession, article: WechatArticle, http) -> str:
    from app.kb.ratelimit import article_fetch_slot

    if article.content:
        return article.content
    # 与 KB 后台回填共用限流 slot：回填不得把前台阅读挤到超时
    async with article_fetch_slot():
        text = await fetch_article_text(http, article.url)
    article.content = text
    article.content_fetched_at = dt.datetime.now(dt.UTC)
    await db.commit()
    return text

"""来源解析层：把「内容从哪来」与「怎么入库」切开。

每种来源实现两个函数，按快/慢分工：
  describe    — 只读本地库，跑在请求里，产出建文档行所需的元信息
  resolve     — 产出纯文本正文，只在后台任务里调（可能要回源抓取）

接入新平台只需在两张注册表里各加一项，入库路径不变。
"""
import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

_TITLE_FALLBACK_CHARS = 40


class SourceNotFound(Exception):
    """源记录不存在，或 source_type 不受支持。"""


@dataclass
class SourceMeta:
    title: str
    source_url: str | None
    published_at: dt.datetime | None


def _as_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as e:
        raise SourceNotFound(f"非法的源 id：{raw}") from e


# ---- 微信公众号文章 ----
async def _describe_wechat_article(db: AsyncSession, source_ref_id: str) -> SourceMeta:
    from app.social.models import WechatArticle

    art = await db.get(WechatArticle, _as_uuid(source_ref_id))
    if art is None:
        raise SourceNotFound("公众号文章不存在")
    return SourceMeta(title=art.title, source_url=art.url, published_at=art.published_at)


async def _resolve_wechat_article(db: AsyncSession, source_ref_id: str, http) -> str:
    from app.social.ingest import fetch_article_content
    from app.social.models import WechatArticle

    art = await db.get(WechatArticle, _as_uuid(source_ref_id))
    if art is None:
        raise SourceNotFound("公众号文章不存在")
    if art.content:
        return art.content
    if http is None:
        raise RuntimeError("正文未缓存且未提供 http client")
    # fetch_article_content 顺手把正文写回源表，下次任何库加这篇都不必再抓
    return await fetch_article_content(db, art, http)


# ---- 7x24 快讯 ----
async def _describe_news_item(db: AsyncSession, source_ref_id: str) -> SourceMeta:
    from app.news.models import NewsItem

    item = await db.get(NewsItem, _as_uuid(source_ref_id))
    if item is None:
        raise SourceNotFound("快讯不存在")
    title = item.title or _prefix_title(item.content)
    return SourceMeta(title=title, source_url=item.url, published_at=item.published_at)


async def _resolve_news_item(db: AsyncSession, source_ref_id: str, http) -> str:
    from app.news.models import NewsItem

    item = await db.get(NewsItem, _as_uuid(source_ref_id))
    if item is None:
        raise SourceNotFound("快讯不存在")
    return item.content


def _prefix_title(content: str) -> str:
    """快讯 title 可空，取正文前 40 字当显示名。"""
    text = (content or "").strip()
    if len(text) <= _TITLE_FALLBACK_CHARS:
        return text or "（空快讯）"
    return text[:_TITLE_FALLBACK_CHARS] + "…"


_DESCRIBERS = {
    "wechat_article": _describe_wechat_article,
    "news_item": _describe_news_item,
}
_RESOLVERS = {
    "wechat_article": _resolve_wechat_article,
    "news_item": _resolve_news_item,
}
SUPPORTED_ITEM_TYPES = frozenset(_DESCRIBERS)


async def describe(db: AsyncSession, source_type: str, source_ref_id: str) -> SourceMeta:
    fn = _DESCRIBERS.get(source_type)
    if fn is None:
        raise SourceNotFound(f"不支持的来源类型：{source_type}")
    return await fn(db, source_ref_id)


async def resolve_text(
    db: AsyncSession, source_type: str, source_ref_id: str, http=None
) -> str:
    fn = _RESOLVERS.get(source_type)
    if fn is None:
        raise SourceNotFound(f"不支持的来源类型：{source_type}")
    return await fn(db, source_ref_id, http)

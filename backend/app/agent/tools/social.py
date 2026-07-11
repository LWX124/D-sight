import datetime as dt

from langchain_core.tools import tool
from sqlalchemy import select

from app.social.models import WechatAccount, WechatArticle


def make_wechat_query(session_factory):
    @tool
    async def wechat_query(account: str = "", keyword: str = "", days: int = 30, limit: int = 20) -> str:
        """查询已订阅微信公众号的文章（标题+正文摘要），用于投研分析。
        account 限定公众号名（模糊），keyword 关键词，days 时间窗天数。"""
        # 同 news_query：绝不向 agent 循环抛异常。
        try:
            since = dt.datetime.now(dt.UTC) - dt.timedelta(days=max(1, days))
            q = (
                select(WechatArticle, WechatAccount.name)
                .join(WechatAccount, WechatArticle.account_id == WechatAccount.id)
                .where(WechatArticle.published_at >= since)
            )
            if account:
                q = q.where(WechatAccount.name.ilike(f"%{account}%"))
            if keyword:
                q = q.where(
                    WechatArticle.title.ilike(f"%{keyword}%")
                    | WechatArticle.content.ilike(f"%{keyword}%")
                    | WechatArticle.digest.ilike(f"%{keyword}%")
                )
            q = q.order_by(WechatArticle.published_at.desc()).limit(min(limit, 50))
            async with session_factory() as db:
                rows = (await db.execute(q)).all()
        except Exception as e:  # noqa: BLE001
            return f"（公众号查询失败：{e}）"
        if not rows:
            return "（时间窗内无相关公众号文章）"
        parts = []
        for art, name in rows:
            body = (art.content or art.digest or "")[:400]
            when = art.published_at.astimezone().strftime("%m-%d %H:%M")
            parts.append(f"[{when}] 《{art.title}》（{name}）\n{body}")
        return "\n\n".join(parts)

    return wechat_query

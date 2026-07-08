import datetime as dt

from langchain_core.tools import tool
from sqlalchemy import select

from app.news.models import NewsItem


def make_news_query(session_factory):
    @tool
    async def news_query(keyword: str = "", hours: int = 24, limit: int = 20) -> str:
        """查询快讯库最近财经新闻。keyword 为空则返回最新；hours 时间窗；用于"当日最新信息总结"。"""
        # tool_guard(safe.py) 仅包同步函数，套在 async 工具上会返回未 await 的协程且
        # 异常永不进 try/except（同 kb_search 的取舍）。故此处不套 tool_guard，改在
        # 函数体内 try/except 返回错误字符串，绝不向 agent 循环抛异常。
        try:
            since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=max(1, hours))
            q = select(NewsItem).where(NewsItem.published_at >= since)
            if keyword:
                q = q.where(NewsItem.content.ilike(f"%{keyword}%"))
            q = q.order_by(NewsItem.published_at.desc()).limit(min(limit, 50))
            async with session_factory() as db:
                rows = (await db.execute(q)).scalars().all()
        except Exception as e:  # noqa: BLE001
            return f"（快讯查询失败：{e}）"
        if not rows:
            return "（时间窗内无相关快讯）"
        return "\n".join(
            f"[{r.published_at.astimezone().strftime('%m-%d %H:%M')}] {r.content}" for r in rows
        )

    return news_query

"""Seed default news sources (idempotent)."""
import asyncio

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.news.models import NewsSource


DEFAULTS = [
    {
        "name": "新浪7x24快讯",
        "type": "sina_live",
        "channel": "news",
        "config": {
            "url": "https://zhibo.sina.com.cn/api/zhibo/feed",
            "params": {"zhibo_id": 152, "page": 1, "page_size": 20, "type": 0},
        },
        "interval_seconds": 120,
    },
]


async def seed_news_sources():
    async with get_sessionmaker()() as db:
        for dflt in DEFAULTS:
            exists = (await db.execute(
                select(NewsSource).where(NewsSource.name == dflt["name"])
            )).scalar_one_or_none()
            if exists:
                continue
            db.add(NewsSource(**dflt, enabled=True))
            print(f"  + news source: {dflt['name']}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_news_sources())

import datetime as dt
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass
class RawItem:
    external_id: str
    content: str
    published_at: dt.datetime
    title: str | None = None
    url: str | None = None


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class NewsSource(ABC):
    @abstractmethod
    async def fetch(self, config: dict) -> list[RawItem]: ...


class FakeSource(NewsSource):
    async def fetch(self, config: dict) -> list[RawItem]:
        raw = config.get("items")
        if raw:
            items = []
            for r in raw:
                r = dict(r)
                pub = r.get("published_at")
                if isinstance(pub, str):
                    r["published_at"] = dt.datetime.fromisoformat(pub)
                items.append(RawItem(**r))
            return items
        now = dt.datetime.now(dt.UTC)
        return [
            RawItem(external_id="fake-1", content="【测试快讯】市场情绪回暖。", published_at=now),
            RawItem(external_id="fake-2", content="【测试快讯】某公司发布财报。", published_at=now),
        ]


class SinaLiveSource(NewsSource):
    """新浪 7x24 快讯。地址/解析路径配置化，默认对应 zhibo feed 形态。"""

    async def fetch(self, config: dict) -> list[RawItem]:
        url = config.get("url", "https://zhibo.sina.com.cn/api/zhibo/feed")
        params = config.get("params", {"zhibo_id": 152, "page": 1, "page_size": 20, "type": 0})
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        # 默认解析：result.data.feed.list[]，字段 id/rich_text/create_time
        feed = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        out = []
        for it in feed:
            ts = it.get("create_time")
            try:
                published = dt.datetime.fromisoformat(ts) if ts else dt.datetime.now(dt.UTC)
            except (ValueError, TypeError):
                published = dt.datetime.now(dt.UTC)
            out.append(RawItem(
                external_id=str(it.get("id")),
                content=it.get("rich_text") or it.get("text") or "",
                published_at=published,
                url=it.get("docurl"),
            ))
        return out


def get_source(type_: str) -> NewsSource:
    if type_ == "fake":
        return FakeSource()
    if type_ == "sina_live":
        return SinaLiveSource()
    raise ValueError(f"未知信源类型：{type_}")

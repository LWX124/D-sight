"""RedFox Provider 实现。

基于 Phase 0 门禁确认的 API 路径：
- 公众号: /story/api/gzhData/searchUser, /story/api/gzhData/queryWorkList,
  /story/api/gzhData/queryArticleDetail
- 小红书: /story/api/xhsUser/searchUser, /story/api/xhsUser/searchArticle, /story/api/xhsUser/queryWorkDetail
- B站:   /story/api/bili/data/accountSearch, /story/api/bili/data/accountWorkList

所有接口均为 POST，认证头 REDFOX_API_KEY。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.social.providers.base import ItemDTO, MetricsDTO, PublisherDTO, SocialProvider
from app.social.wechat.parser import html_to_text

logger = logging.getLogger(__name__)

_BASE_URL = "https://redfox.hk"

# 各平台搜索账号的 API 路径
_SEARCH_ACCOUNT_PATHS = {
    "wechat": "/story/api/gzhData/searchUser",
    "xiaohongshu": "/story/api/xhsUser/searchUser",
    "bilibili": "/story/api/bili/data/accountSearch",
}

# 各平台获取账号作品列表的 API 路径（None = 不支持）
_ITEM_LIST_PATHS = {
    "wechat": "/story/api/gzhData/queryWorkList",
    "xiaohongshu": None,  # 无账号作品列表接口
    "bilibili": "/story/api/bili/data/accountWorkList",
}

# 各平台获取作品详情的 API 路径（None = 列表已包含详情）
_ITEM_DETAIL_PATHS = {
    "wechat": "/story/api/gzhData/queryArticleDetail",
    "xiaohongshu": "/story/api/xhsUser/queryWorkDetail",
    "bilibili": None,
}

_CAPABILITIES = {
    "wechat": {
        "account_item_list": True,
        "publisher_search": True,
        "item_search": False,
        "detail": True,
        "vertical_hot_feed": False,
    },
    "xiaohongshu": {
        "account_item_list": False,
        "publisher_search": True,
        "item_search": True,
        "detail": True,
        "vertical_hot_feed": True,
        "missing_reason": "RedFox does not expose a Xiaohongshu account item-list API",
    },
    "bilibili": {
        "account_item_list": True,
        "publisher_search": True,
        "item_search": False,
        "detail": False,
        "vertical_hot_feed": False,
    },
}


def is_allowed_wechat_article_url(url: str | None) -> bool:
    """Accept only an unambiguous URL on the exact HTTPS WeChat article origin."""
    if not url or url != url.strip() or any(ord(char) < 32 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname == "mp.weixin.qq.com"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


class RedFoxProvider(SocialProvider):
    """RedFox 社媒内容 Provider。"""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = _BASE_URL,
        timeout: float = 30,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "REDFOX_API_KEY": api_key,
            "Content-Type": "application/json",
        }
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._raw_records: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        """Close the reusable HTTP client when this provider owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "RedFoxProvider":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def drain_raw_records(self) -> list[dict[str, Any]]:
        """Return captured JSON responses once for bounded audit persistence."""
        records, self._raw_records = self._raw_records, []
        return records

    async def _post(self, path: str, body: dict, *, platform: str) -> dict:
        """发起 POST 请求并返回 data 字段。"""
        url = f"{self._base_url}{path}"
        resp = await self._client.post(url, headers=self._headers, json=body)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, dict):
            self._raw_records.append({"platform": platform, "operation": path, "payload": result})
        if not isinstance(result, dict) or result.get("code") != 2000:
            message = result.get("msg", "unknown") if isinstance(result, dict) else "invalid JSON"
            raise RuntimeError(f"RedFox API error: {message}")
        data = result.get("data", {})
        return data if isinstance(data, dict) else {"list": data}

    async def search_publishers(self, platform: str, query: str) -> list[PublisherDTO]:
        path = _SEARCH_ACCOUNT_PATHS.get(platform)
        if not path:
            return []

        body = {"keyword": query, "offset": 0}
        # B站使用 page/pageSize 而非 offset
        if platform == "bilibili":
            body = {"keyword": query, "page": "1", "pageSize": 10}

        data = await self._post(path, body, platform=platform)

        # 各平台的账号列表字段名不同
        if platform == "bilibili":
            accounts = data.get("accountList", [])
        else:
            accounts = data.get("list", [])

        return [self._map_publisher(platform, acc) for acc in accounts]

    def _map_publisher(self, platform: str, raw: dict) -> PublisherDTO:
        """将原始数据映射为 PublisherDTO。"""
        if platform == "wechat":
            return PublisherDTO(
                platform="wechat",
                external_id=raw.get("account", ""),
                name=raw.get("accountName", ""),
                avatar=raw.get("avatarUrl"),
                description=raw.get("description"),
                provider="redfox",
                platform_metadata={
                    "redfox_index": raw.get("redfoxIndex"),
                    "tags": raw.get("tags"),
                    "verify_info": raw.get("verifyInfo"),
                    "last_publish_time": raw.get("lastPublishTime"),
                },
            )
        elif platform == "xiaohongshu":
            return PublisherDTO(
                platform="xiaohongshu",
                external_id=raw.get("accountId", ""),
                name=raw.get("accountName", ""),
                avatar=raw.get("accountAvatar"),
                description=raw.get("accountDesc"),
                provider="redfox",
                platform_metadata={
                    "fans": raw.get("accountFans"),
                    "likes": raw.get("accountLikes"),
                    "total_works": raw.get("accountTotalWorks"),
                    "city": raw.get("city"),
                    "province": raw.get("province"),
                },
            )
        elif platform == "bilibili":
            return PublisherDTO(
                platform="bilibili",
                external_id=str(raw.get("mid", "")),
                name=raw.get("name", ""),
                avatar=raw.get("face"),
                description=raw.get("sign"),
                provider="redfox",
                platform_metadata={
                    "follower": raw.get("follower"),
                    "like_count": raw.get("likeCount"),
                    "play_count": raw.get("playCount"),
                    "video_count": raw.get("videoCount"),
                    "type": raw.get("type"),
                    "type_v2": raw.get("typeV2"),
                    "official_title": raw.get("officialTitle"),
                },
            )
        return PublisherDTO(platform=platform, external_id="", name="")

    async def fetch_publisher_items(
        self, publisher: PublisherDTO, since: datetime | None = None
    ) -> list[ItemDTO]:
        path = _ITEM_LIST_PATHS.get(publisher.platform)
        if not path:
            if publisher.platform == "xiaohongshu":
                raise NotImplementedError(
                    "RedFox has no Xiaohongshu account item-list API; use search_items"
                )
            raise ValueError(f"unsupported RedFox platform: {publisher.platform}")

        body: dict
        if publisher.platform == "wechat":
            body = {"account": publisher.external_id, "offset": 0, "sortType": "_2"}
        elif publisher.platform == "bilibili":
            body = {"mid": publisher.external_id, "page": "1", "pageSize": 20, "order": "time"}
        else:
            return []

        data = await self._post(path, body, platform=publisher.platform)

        if publisher.platform == "bilibili":
            items = data.get("workList", [])
        else:
            items = data.get("list", [])

        mapped = [self._map_item(publisher.platform, item) for item in items]
        if since is None:
            return mapped
        normalized_since = _as_utc(since)
        return [
            item
            for item in mapped
            if item.published_at is None or _as_utc(item.published_at) >= normalized_since
        ]

    async def search_items(
        self,
        platform: str,
        query: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[ItemDTO]:
        """Search Xiaohongshu works through the verified searchArticle API."""
        if platform != "xiaohongshu":
            raise NotImplementedError(f"RedFox item search is unavailable for {platform}")
        keyword = query.strip()
        if not keyword:
            raise ValueError("query must not be empty")
        data = await self._post(
            "/story/api/xhsUser/searchArticle",
            {"keyword": keyword, "offset": max(0, offset)},
            platform=platform,
        )
        rows = data.get("list", [])
        if not isinstance(rows, list):
            raise RuntimeError("RedFox API error: invalid searchArticle list")
        return [self._map_item(platform, row) for row in rows[: max(1, min(limit, 50))]]

    async def fetch_vertical_hot_feed(
        self,
        platform: str,
        source_key: str,
        window: str = "7d",
        *,
        limit: int = 20,
    ) -> list[ItemDTO]:
        """Discover topic content; RedFox has no first-party financial leaderboard."""
        days = {"24h": 1, "3d": 3, "7d": 7}.get(window)
        if days is None:
            raise ValueError("window must be one of: 24h, 3d, 7d")
        items = await self.search_items(platform, source_key, limit=limit)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [
            item
            for item in items
            if item.published_at is None or _as_utc(item.published_at) >= cutoff
        ]

    def _map_item(self, platform: str, raw: dict) -> ItemDTO:
        """将原始数据映射为 ItemDTO。"""
        if platform == "wechat":
            published_at = _parse_time(raw.get("publishTime"))
            return ItemDTO(
                platform="wechat",
                external_id=raw.get("workUuid", ""),
                content_type="article",
                title=raw.get("title"),
                digest=raw.get("summary") or raw.get("memo"),
                cover_url=raw.get("coverUrl"),
                url=raw.get("workUrl") or raw.get("sourceUrl"),
                published_at=published_at,
                platform_metadata={
                    "account_type": raw.get("accountType"),
                    "author": raw.get("author"),
                    "is_original": raw.get("isOriginal"),
                    "order_num": raw.get("orderNum"),
                    "publish_location": raw.get("publishLocation"),
                    "sync_time": raw.get("syncTime"),
                },
                metrics=MetricsDTO(
                    view_count=raw.get("readCount"),
                    like_count=raw.get("likeCount"),
                    comment_count=raw.get("commentCount"),
                    share_count=raw.get("shareCount"),
                    collect_count=raw.get("collectCount"),
                    raw={
                        "watch_count": raw.get("watchCount"),
                        "reward_count": raw.get("rewardCount"),
                    },
                ),
            )
        elif platform == "xiaohongshu":
            published_at = _parse_time(raw.get("workPublishTime"))
            return ItemDTO(
                platform="xiaohongshu",
                external_id=raw.get("workId", ""),
                content_type="video" if "video" in str(raw.get("workType", "")).lower() else "post",
                title=raw.get("workTitle"),
                body_text=raw.get("workDesc"),
                cover_url=raw.get("coverUrl"),
                url=raw.get("workUrl"),
                published_at=published_at,
                platform_metadata={
                    "account_nickname": raw.get("accountNickname"),
                    "account_userid": raw.get("accountUserid"),
                    "work_type": raw.get("workType"),
                },
                metrics=MetricsDTO(
                    like_count=raw.get("workLikedCount"),
                    comment_count=raw.get("workCommentsCount"),
                    share_count=raw.get("workSharedCount"),
                    collect_count=raw.get("workCollectedCount"),
                ),
            )
        elif platform == "bilibili":
            published_at = _parse_time(raw.get("created"))
            return ItemDTO(
                platform="bilibili",
                external_id=raw.get("bvId", ""),
                content_type="video",
                title=raw.get("title"),
                body_text=raw.get("description"),
                cover_url=raw.get("picUrl"),
                url=f"https://www.bilibili.com/video/{raw.get('bvId')}"
                if raw.get("bvId")
                else None,
                published_at=published_at,
                platform_metadata={
                    "author": raw.get("author"),
                    "duration": raw.get("duration"),
                    "first_type": raw.get("firstType"),
                    "second_type": raw.get("secondType"),
                    "tag_names": raw.get("tagNames"),
                },
                metrics=MetricsDTO(
                    view_count=raw.get("playCount"),
                    like_count=raw.get("likeCount"),
                    comment_count=raw.get("commentCount"),
                    share_count=raw.get("shareCount"),
                    collect_count=raw.get("favoriteCount"),
                    raw={
                        "coin_count": raw.get("coinCount"),
                        "video_review": raw.get("videoReview"),  # 弹幕数
                        "interaction_quantity": raw.get("interactionQuantity"),
                    },
                ),
            )
        return ItemDTO(platform=platform, external_id="", content_type="article")

    async def fetch_item_detail(self, item: ItemDTO) -> ItemDTO:
        path = _ITEM_DETAIL_PATHS.get(item.platform)
        if not path:
            return item  # 详情已包含在列表中

        if item.platform == "wechat":
            if not is_allowed_wechat_article_url(item.url):
                raise ValueError("WeChat article detail requires an allowed article URL")
            data = await self._post(path, {"url": item.url}, platform=item.platform)
            content = data.get("content")
            return ItemDTO(
                platform=item.platform,
                external_id=item.external_id,
                content_type=item.content_type,
                title=item.title,
                body_text=html_to_text(content) if isinstance(content, str) else None,
                digest=item.digest,
                cover_url=item.cover_url,
                url=item.url,
                published_at=item.published_at,
                platform_metadata=item.platform_metadata,
                metrics=item.metrics,
            )

        if item.platform == "xiaohongshu":
            data = await self._post(path, {"workId": item.external_id}, platform=item.platform)
            return self._map_item("xiaohongshu", data)

        return item

    def capabilities(self, platform: str) -> dict:
        return dict(
            _CAPABILITIES.get(
                platform,
                {
                    "account_item_list": False,
                    "publisher_search": False,
                    "item_search": False,
                    "detail": False,
                    "vertical_hot_feed": False,
                    "missing_reason": "unsupported platform",
                },
            )
        )


def _parse_time(time_str: Any) -> datetime | None:
    """解析时间字符串，支持多种格式。"""
    if time_str in (None, ""):
        return None
    if isinstance(time_str, int | float):
        value = time_str / 1000 if time_str > 10_000_000_000 else time_str
        return datetime.fromtimestamp(value, tz=timezone.utc)
    time_str = str(time_str)
    try:
        parsed = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return _as_utc(parsed)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(time_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

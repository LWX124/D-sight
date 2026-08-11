"""Provider Adapter 基类和 DTO。

所有 Provider（RedFox、微博登录态、公众号扫码）实现 SocialProvider 接口。
DTO 是 Provider 与统一 CRUD 层之间的桥梁，不含平台特有字段。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PublisherDTO:
    """统一发布者 DTO。"""
    platform: str          # wechat/weibo/xiaohongshu/bilibili
    external_id: str       # fakeid/uid/workId/mid
    name: str
    avatar: str | None = None
    description: str | None = None
    profile_url: str | None = None
    provider: str = ""     # redfox/wechat_mp/weibo
    provider_ref: str | None = None
    platform_metadata: dict = field(default_factory=dict)


@dataclass
class MetricsDTO:
    """统一互动指标 DTO。"""
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    collect_count: int | None = None
    provider_rank: int | None = None
    raw: dict = field(default_factory=dict)  # 平台特有指标


@dataclass
class ItemDTO:
    """统一内容 DTO。"""
    platform: str
    external_id: str
    content_type: str          # article/post/video
    title: str | None = None
    body_text: str | None = None
    transcript_text: str | None = None
    digest: str | None = None
    cover_url: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    platform_metadata: dict = field(default_factory=dict)
    metrics: MetricsDTO = field(default_factory=MetricsDTO)


class SocialProvider(ABC):
    """社媒 Provider 统一接口。"""

    @abstractmethod
    async def search_publishers(self, platform: str, query: str) -> list[PublisherDTO]:
        """搜索发布者。"""
        ...

    @abstractmethod
    async def fetch_publisher_items(
        self, publisher: PublisherDTO, since: datetime | None = None
    ) -> list[ItemDTO]:
        """获取发布者的作品列表。"""
        ...

    @abstractmethod
    async def fetch_item_detail(self, item: ItemDTO) -> ItemDTO:
        """获取单个作品的详情（正文/字幕/完整指标）。"""
        ...

    async def search_items(
        self,
        platform: str,
        query: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[ItemDTO]:
        """Search content when a platform has no publisher-item-list API.

        Providers must advertise this optional capability with ``item_search``.
        Returning an empty list is reserved for a valid search with no results;
        unsupported platforms raise explicitly so callers cannot mistake a
        missing capability for a successful empty fetch.
        """
        raise NotImplementedError(f"{platform} does not support item search")

    async def fetch_vertical_hot_feed(
        self,
        platform: str,
        source_key: str,
        window: str = "7d",
        *,
        limit: int = 20,
    ) -> list[ItemDTO]:
        """Fetch a topic feed for AIHot-compatible providers.

        The initial implementation is keyword discovery, not a provider-owned
        financial leaderboard. ``window`` is kept in the contract for callers;
        providers may filter locally when the upstream has no window parameter.
        """
        del window
        return await self.search_items(platform, source_key, limit=limit)

    @abstractmethod
    def capabilities(self, platform: str) -> dict:
        """返回该平台的能力声明。

        示例：
        {
            "account_item_list": True,   # 是否支持获取账号作品列表
            "search": True,              # 是否支持搜索
            "detail": True,              # 是否支持获取详情
        }
        """
        ...

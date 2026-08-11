"""微博登录态 Provider 适配。

将现有 app/social/weibo/client.py 的采集逻辑适配为统一 SocialProvider 接口。
微博使用独立的登录态采集链路，不通过 RedFox。
"""
import logging
from datetime import datetime

from app.social.providers.base import ItemDTO, MetricsDTO, PublisherDTO, SocialProvider

logger = logging.getLogger(__name__)


class WeiboProvider(SocialProvider):
    """微博登录态 Provider。

    实际采集通过现有 WeiboClient + parser 完成，此适配层负责映射 DTO。
    搜索功能不可用（微博无搜索 API），仅支持已知账号的作品列表。
    """

    async def search_publishers(self, platform: str, query: str) -> list[PublisherDTO]:
        raise NotImplementedError("Weibo publisher search is unavailable")

    async def fetch_publisher_items(
        self, publisher: PublisherDTO, since: datetime | None = None
    ) -> list[ItemDTO]:
        """微博采集需要登录态与数据库账号，由统一刷新编排器执行。"""
        raise NotImplementedError("Weibo collection is orchestrated by social.refresh")

    async def fetch_item_detail(self, item: ItemDTO) -> ItemDTO:
        # 微博详情已包含在列表中
        return item

    def capabilities(self, platform: str) -> dict:
        return {
            "account_item_list": True,
            "publisher_search": False,
            "item_search": False,
            "detail": False,
            "vertical_hot_feed": False,
        }

    @staticmethod
    def from_weibo_profile(profile) -> PublisherDTO:
        """从现有 WeiboProfile 映射为 PublisherDTO。"""
        return PublisherDTO(
            platform="weibo",
            external_id=profile.uid,
            name=profile.name,
            avatar=profile.avatar,
            description=profile.description,
            provider="weibo",
            provider_ref=profile.container_id,
        )

    @staticmethod
    def from_weibo_post(post) -> ItemDTO:
        """从现有 RawWeiboPost 映射为 ItemDTO。"""
        return ItemDTO(
            platform="weibo",
            external_id=post.external_id,
            content_type="post",
            body_text=post.content,
            published_at=post.published_at,
            platform_metadata={
                "bid": post.bid,
                "is_repost": getattr(post, "is_repost", False),
                "is_pinned": getattr(post, "is_pinned", False),
                "media": post.media,
            },
            metrics=MetricsDTO(),  # 微博列表不返回互动指标
        )

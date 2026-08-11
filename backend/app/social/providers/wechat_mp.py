"""公众号扫码采集 Provider 适配。

将现有 app/social/wechat/client.py 的采集逻辑适配为统一 SocialProvider 接口。
公众号使用扫码登录 + appmsgpublish 接口采集。
"""
import logging
from datetime import datetime

from app.social.providers.base import ItemDTO, MetricsDTO, PublisherDTO, SocialProvider

logger = logging.getLogger(__name__)


class WechatMpProvider(SocialProvider):
    """公众号扫码采集 Provider。

    搜索通过现有 search_biz 接口实现。
    作品列表通过现有 WeChatClient 的文章接口实现。
    """

    async def search_publishers(self, platform: str, query: str) -> list[PublisherDTO]:
        raise NotImplementedError("Wechat MP search requires a credential-bound context")

    async def fetch_publisher_items(
        self, publisher: PublisherDTO, since: datetime | None = None
    ) -> list[ItemDTO]:
        raise NotImplementedError("Wechat MP collection is orchestrated by social.refresh")

    async def fetch_item_detail(self, item: ItemDTO) -> ItemDTO:
        # 公众号详情已包含在列表中
        return item

    def capabilities(self, platform: str) -> dict:
        return {
            "account_item_list": True,
            "publisher_search": False,
            "item_search": False,
            "detail": False,
            "vertical_hot_feed": False,
            "missing_reason": "Wechat MP search requires a credential-bound collection context",
        }

    @staticmethod
    def from_wechat_account(account) -> PublisherDTO:
        """从现有 WechatAccount 映射为 PublisherDTO。"""
        return PublisherDTO(
            platform="wechat",
            external_id=account.fakeid,
            name=account.name,
            avatar=account.avatar,
            description=account.signature,
            provider="wechat_mp",
        )

    @staticmethod
    def from_wechat_article(article) -> ItemDTO:
        """从现有 WechatArticle 映射为 ItemDTO。"""
        return ItemDTO(
            platform="wechat",
            external_id=article.external_id,
            content_type="article",
            title=article.title,
            digest=article.digest,
            cover_url=article.cover_url,
            url=article.url,
            body_text=article.content,
            published_at=article.published_at,
            platform_metadata={},
            metrics=MetricsDTO(),
        )

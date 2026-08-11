import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---- 旧接口兼容（保留） ----

class SubscribeIn(BaseModel):
    fakeid: str
    name: str
    avatar: str | None = None


class AccountOut(BaseModel):
    id: str
    fakeid: str
    name: str
    avatar: str | None


class SubscriptionOut(BaseModel):
    id: str
    account_id: str
    fakeid: str
    name: str
    avatar: str | None
    enabled: bool


class ArticleOut(BaseModel):
    id: str
    account_id: str
    title: str
    digest: str | None
    cover_url: str | None
    url: str
    content: str | None
    published_at: str


class CredentialOut(BaseModel):
    id: str
    nickname: str
    avatar: str | None
    status: str
    expires_at: str


# ---- Phase 2: 统一订阅动态 ----

class PublisherBrief(BaseModel):
    """发布者简要信息（嵌入 FeedItem）。"""
    id: str
    name: str
    avatar: str | None
    platform: str


class FeedItemOut(BaseModel):
    """统一 Feed 内容项。"""
    id: str
    platform: str
    external_id: str
    content_type: str
    title: str | None
    digest: str | None
    cover_url: str | None
    url: str | None
    published_at: str | None
    publisher: PublisherBrief


class FeedPageOut(BaseModel):
    items: list[FeedItemOut]
    next_before: str | None


class FeedItemDetailOut(FeedItemOut):
    body_text: str | None
    transcript_text: str | None


class UnifiedSubscribeIn(BaseModel):
    """跨平台订阅请求。"""
    publisher_id: uuid.UUID | None = None
    platform: Literal["wechat", "weibo", "xiaohongshu", "bilibili"] | None = None
    external_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    avatar: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_identity(self) -> "UnifiedSubscribeIn":
        if self.publisher_id is None and not all((self.platform, self.external_id, self.name)):
            raise ValueError("publisher_id 或 platform/external_id/name 必须提供")
        for field_name in ("external_id", "name"):
            value = getattr(self, field_name)
            if value is not None:
                value = value.strip()
                if not value:
                    raise ValueError(f"{field_name} 不能为空")
                setattr(self, field_name, value)
        return self


class UnifiedSubscriptionOut(BaseModel):
    """跨平台订阅响应。"""
    id: str
    publisher_id: str
    platform: str
    external_id: str
    name: str
    avatar: str | None
    enabled: bool


class PublisherSearchOut(BaseModel):
    """搜索发布者响应。"""
    platform: str
    external_id: str
    name: str
    avatar: str | None
    description: str | None
    provider: str


class BookmarkIn(BaseModel):
    item_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=2000)

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WechatCredential(Base):
    __tablename__ = "wechat_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(Text, nullable=False)       # Fernet 加密
    cookies: Mapped[str] = mapped_column(Text, nullable=False)     # Fernet 加密
    nickname: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active/expired
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WechatAccount(Base):
    __tablename__ = "wechat_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fakeid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(512))
    signature: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WechatArticle(Base):
    __tablename__ = "wechat_articles"
    __table_args__ = (UniqueConstraint("account_id", "external_id", name="uq_wechat_account_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wechat_accounts.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)  # = aid
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 文字消息无标题，接口把全文塞进 title，长度无上限
    digest: Mapped[str | None] = mapped_column(String(1024))
    cover_url: Mapped[str | None] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)  # 纯文本正文，懒抓填充
    content_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WechatSubscription(Base):
    __tablename__ = "wechat_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_wechat_sub_user_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wechat_accounts.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WeiboCredential(Base):
    __tablename__ = "weibo_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cookies: Mapped[str] = mapped_column(Text, nullable=False)
    weibo_uid: Mapped[str | None] = mapped_column(String(32))
    nickname: Mapped[str | None] = mapped_column(String(128))
    avatar: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WeiboAccount(Base):
    __tablename__ = "weibo_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    uid: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    container_id: Mapped[str] = mapped_column(String(128), nullable=False)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    last_sync_error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WeiboPost(Base):
    __tablename__ = "weibo_posts"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_weibo_account_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("weibo_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    bid: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    media: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    published_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    captured_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WeiboSubscription(Base):
    __tablename__ = "weibo_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_weibo_sub_user_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("weibo_accounts.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

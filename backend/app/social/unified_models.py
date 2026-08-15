"""统一社媒数据模型。

对应设计文档 §7.1 的 5 张核心表。
"""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class SocialPublisher(Base):
    """平台发布者主表。"""
    __tablename__ = "social_publishers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)  # wechat/weibo/xiaohongshu/bilibili
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(String(1024))
    provider: Mapped[str | None] = mapped_column(String(32))  # redfox/wechat_mp/weibo
    provider_ref: Mapped[str | None] = mapped_column(String(256))
    last_synced_at = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(16))
    sync_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    sync_provider: Mapped[str | None] = mapped_column(String(32))
    last_sync_error_code: Mapped[str | None] = mapped_column(String(64))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    next_sync_at = mapped_column(DateTime(timezone=True))
    platform_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_social_publishers_platform_ext"),
        Index("ix_social_publishers_platform", "platform"),
        Index(
            "ix_social_publishers_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    items = relationship("SocialItem", back_populates="publisher", lazy="raise")
    subscriptions = relationship("SocialSubscription", back_populates="publisher", lazy="raise")
    identities = relationship(
        "SocialPublisherIdentity", back_populates="publisher", lazy="raise"
    )


class SocialPublisherIdentity(Base):
    """One upstream identity belonging to a canonical global publisher."""

    __tablename__ = "social_publisher_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("social_publishers.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'active'")
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    next_due_at = mapped_column(DateTime(timezone=True))
    requested_at = mapped_column(DateTime(timezone=True))
    waiting_since_at = mapped_column(DateTime(timezone=True))
    last_attempt_at = mapped_column(DateTime(timezone=True))
    last_success_at = mapped_column(DateTime(timezone=True))
    last_checked_at = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "platform",
            "external_id",
            name="uq_social_identity_provider_platform_external",
        ),
        CheckConstraint(
            "status IN ('active','coverage_gap','waiting_capacity',"
            "'identity_unresolved','identity_ambiguous','disabled')",
            name="ck_social_identity_status",
        ),
        Index("ix_social_identity_publisher", "publisher_id"),
        Index("ix_social_identity_due", "status", "next_due_at"),
        Index("ix_social_identity_waiting", "status", "waiting_since_at"),
    )

    publisher = relationship("SocialPublisher", back_populates="identities")


class SocialProviderDailyUsage(Base):
    """Durable hard limit for real provider requests, including failures."""

    __tablename__ = "social_provider_daily_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    usage_date = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    updated_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "provider", "usage_date", name="uq_social_provider_daily_usage"
        ),
        CheckConstraint(
            "request_count >= 0", name="ck_social_provider_daily_usage_nonnegative"
        ),
        Index("ix_social_provider_daily_usage_date", "usage_date"),
    )


class SocialItem(Base):
    """平台内容主表。"""
    __tablename__ = "social_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_publishers.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)  # article/post/video
    title: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    digest: Mapped[str | None] = mapped_column(String(2048))
    cover_url: Mapped[str | None] = mapped_column(String(1024))
    url: Mapped[str | None] = mapped_column(String(1024))
    published_at = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    body_fetched_at = mapped_column(DateTime(timezone=True))
    body_expires_at = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    enrichment_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    platform_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_social_items_platform_ext"),
        Index(
            "ix_social_items_publisher_feed",
            "publisher_id",
            published_at.desc(),
            id.desc(),
        ),
        Index("ix_social_items_content_hash", "content_hash"),
        Index("ix_social_items_body_expires_at", "body_expires_at"),
        Index("ix_social_items_publisher_id", "publisher_id"),
        Index("ix_social_items_published_at", "published_at"),
        Index(
            "ix_social_items_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_social_items_digest_trgm",
            "digest",
            postgresql_using="gin",
            postgresql_ops={"digest": "gin_trgm_ops"},
        ),
    )

    publisher = relationship("SocialPublisher", back_populates="items")
    metrics = relationship("SocialItemMetricSnapshot", back_populates="item", lazy="raise")
    media = relationship("SocialItemMedia", back_populates="item", lazy="raise")


class SocialItemMetricSnapshot(Base):
    """互动指标快照。"""
    __tablename__ = "social_item_metric_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_items.id", ondelete="CASCADE"), nullable=False)
    captured_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    view_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    share_count: Mapped[int | None] = mapped_column(Integer)
    collect_count: Mapped[int | None] = mapped_column(Integer)
    provider_rank: Mapped[int | None] = mapped_column(Integer)
    raw_metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("item_id", "captured_at", name="uq_social_metrics_item_captured"),
        Index("ix_social_metrics_item_captured", "item_id", "captured_at"),
    )

    item = relationship("SocialItem", back_populates="metrics")


class SocialSubscription(Base):
    """用户订阅关系。"""
    __tablename__ = "social_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    publisher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_publishers.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "publisher_id", name="uq_social_sub_user_publisher"),
        Index("ix_social_subscriptions_user_id", "user_id"),
        Index(
            "ix_social_subscriptions_user_enabled_publisher",
            "user_id",
            "enabled",
            "publisher_id",
        ),
    )

    publisher = relationship("SocialPublisher", back_populates="subscriptions")


class SocialItemMedia(Base):
    """内容媒体附件。"""
    __tablename__ = "social_item_media"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_items.id", ondelete="CASCADE"), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)  # image/video/audio
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_social_media_item_id", "item_id"),)

    item = relationship("SocialItem", back_populates="media")


class ContentBookmark(Base):
    """A user's durable reference to a social item."""

    __tablename__ = "content_bookmarks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_items.id", ondelete="CASCADE"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_content_bookmarks_user_item"),
        Index("ix_content_bookmarks_user_id", "user_id"),
        Index("ix_content_bookmarks_item_id", "item_id"),
        Index("ix_content_bookmarks_user_created", "user_id", created_at.desc()),
    )

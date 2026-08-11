"""AIHot ORM Models。"""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class HotSourceMembership(Base):
    """金融信源池成员。"""
    __tablename__ = "hot_source_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_publishers.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'redfox'")
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'market'")
    )
    source_key: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    added_by = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("publisher_id", name="uq_hot_source_publisher"),
        UniqueConstraint(
            "provider", "platform", "source_key", name="uq_hot_source_search_key"
        ),
        CheckConstraint(
            "publisher_id IS NOT NULL OR source_key IS NOT NULL",
            name="ck_hot_source_target",
        ),
        Index("ix_hot_source_memberships_category", "category"),
        Index("ix_hot_source_memberships_enabled", "enabled"),
    )

    publisher = relationship("SocialPublisher", lazy="raise")


class HotRun(Base):
    """AIHot 批次采集记录。"""
    __tablename__ = "hot_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, server_default="redfox")
    source_key: Mapped[str | None] = mapped_column(String(128))
    run_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'scheduled'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    started_at = mapped_column(DateTime(timezone=True))
    finished_at = mapped_column(DateTime(timezone=True))
    items_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items_new: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    formula_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_hot_runs_status_finished", "status", finished_at.desc()),
    )

    rankings = relationship("HotRanking", back_populates="run", lazy="raise")


class HotItemSource(Base):
    """Provenance linking discovered content to an explicitly enabled hot source."""

    __tablename__ = "hot_item_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_items.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hot_source_memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    discovered_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("item_id", "source_id", name="uq_hot_item_source"),
        Index(
            "ix_hot_item_sources_source_discovered", "source_id", discovered_at.desc()
        ),
    )


class HotRanking(Base):
    """AIHot 排名。"""
    __tablename__ = "hot_rankings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hot_runs.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("social_items.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    window: Mapped[str] = mapped_column(String(8), nullable=False)  # 24h/3d/7d
    aihot_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_rank: Mapped[int | None] = mapped_column(Integer)
    rank_delta: Mapped[int | None] = mapped_column(Integer)
    platform_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    momentum_score: Mapped[float] = mapped_column(Float, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")
    computed_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "item_id", "window", name="uq_hot_ranking_run_item_window"),
        Index(
            "ix_hot_rankings_run_window_category_rank",
            "run_id",
            "window",
            "category",
            "rank",
        ),
        Index("ix_hot_rankings_computed_at", "computed_at"),
    )

    run = relationship("HotRun", back_populates="rankings")
    item = relationship("SocialItem", lazy="raise")


class ProviderCallLog(Base):
    """Provider 调用日志。"""
    __tablename__ = "provider_call_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    response_size: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    estimated_cost = mapped_column(Numeric(10, 4))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_provider_call_logs_created_at", "created_at"),
        Index(
            "ix_provider_call_logs_provider_operation_created",
            "provider",
            "operation",
            created_at.desc(),
        ),
    )


class ContentEnrichment(Base):
    """Versioned AI interpretation. It never changes measured heat."""

    __tablename__ = "content_enrichments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_items.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_financial: Mapped[bool | None] = mapped_column(Boolean)
    relevance_confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    assets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    generated_at = mapped_column(DateTime(timezone=True))
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("item_id", "version", name="uq_content_enrichment_item_version"),
        Index("ix_content_enrichments_category", "category"),
    )


class ProviderRawRecord(Base):
    """Short-lived raw provider response for audit/debugging."""

    __tablename__ = "provider_raw_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_provider_raw_records_expires_at", "expires_at"),)

import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIM = 1024


class Kb(Base):
    __tablename__ = "kb"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_slug: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KbSource(Base):
    """知识库订阅的内容源。当前仅 wechat_account，未来可扩 xhs_user 等。"""

    __tablename__ = "kb_sources"
    __table_args__ = (
        UniqueConstraint("kb_id", "source_type", "source_ref_id", name="uq_kb_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 冗余存一份显示名，列订阅时免 join 源表
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # pending / syncing / ready / failed / limited
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        UniqueConstraint("kb_id", "source_type", "source_ref_id", name="uq_kb_doc_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # 仅上传文档有值；社媒/快讯为 NULL
    filename: Mapped[str | None] = mapped_column(String(255))
    # 入库时的文本快照。详情页展示它而非回源重抓——检索命中的就是这份文本，
    # 展示与检索必须一致（chunk 间有重叠，拼不回原文，故单独存一份）。
    text: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="upload", server_default="upload", index=True
    )
    # 源表主键（字符串化的 uuid）。upload 为 NULL，借 Postgres「NULL 互不相等」
    # 绕过唯一约束，同名文件仍可重复上传。
    source_ref_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    kb_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 向量复用键：同一文本在任何库里只需算一次 embedding。见 embedding_cache.py。
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbSubscription(Base):
    __tablename__ = "kb_subscriptions"
    __table_args__ = (UniqueConstraint("kb_id", "user_id", name="uq_kb_subscription"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

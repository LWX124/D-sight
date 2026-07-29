"""深度分析报告 ORM 模型。

表结构对应设计文档第 4 节；字段注释说明每列语义。
每次状态推进必须携带 claim_token + lease_version，防止失联 worker 写入。
"""
import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DeepAnalysisReport(Base):
    __tablename__ = "deep_analysis_reports"
    __table_args__ = (
        # 同一用户同一活跃请求只允许一条（market+normalized_ticker+analysis_version 组合）。
        # UniqueConstraint 不支持 partial where，用 unique Index + postgresql_where 实现。
        Index(
            "uq_deep_analysis_active_request",
            "user_id",
            "market",
            "normalized_ticker",
            "analysis_version",
            unique=True,
            postgresql_where="status IN ('pending','running','retry_wait') AND deleted_at IS NULL",
        ),
        # 幂等键唯一
        Index(
            "uq_deep_analysis_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        # 完成态必须有 result
        CheckConstraint(
            "(status = 'completed') = (result IS NOT NULL)",
            name="chk_deep_analysis_completed_result",
        ),
        # worker 认领索引
        Index(
            "ix_deep_analysis_worker_claim",
            "next_retry_at",
            "created_at",
            postgresql_where="status IN ('pending','retry_wait')",
        ),
        # 失联检测索引
        Index(
            "ix_deep_analysis_stale_running",
            "heartbeat_at",
            postgresql_where="status = 'running'",
        ),
        # 用户历史索引
        Index(
            "ix_deep_analysis_owner_history",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    market: Mapped[str] = mapped_column(String(4), nullable=False)  # A / HK / US
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)  # 用户原始输入
    normalized_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- 任务状态机 ---
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)

    # --- 执行租约 ---
    worker_id: Mapped[str | None] = mapped_column(String(128))
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- 幂等 ---
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))

    # --- 时间戳 ---
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # --- 结果 ---
    conclusion_status: Mapped[str | None] = mapped_column(String(24))
    result: Mapped[dict | None] = mapped_column(JSONB)
    data_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[dict | None] = mapped_column(JSONB)

    # --- 积分 ---
    credit_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="reserved"
    )  # reserved / settled / released / exempt
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settled_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

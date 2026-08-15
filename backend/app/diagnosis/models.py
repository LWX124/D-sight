"""
Diagnosis Models

诊断档案、不可变版本和 EvidencePack 持久化模型。
"""

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from .schemas import DiagnosisFileStatus as DiagnosisFileStatus
from .schemas import DiagnosisRunStatus as DiagnosisRunStatus


class DiagnosisFile(Base):
    """
    诊断档案

    长期存在的标的诊断记录，一个 DiagnosisFile 对应一个标的。
    """
    __tablename__ = "diagnosis_files"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_diagnosis_file_owner_id"),
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["diagnosis_versions.id", "diagnosis_versions.diagnosis_file_id"],
            name="fk_diagnosis_file_current_version",
            ondelete="SET NULL (current_version_id)",
            use_alter=True,
        ),
        CheckConstraint(
            "status IN ('active','archived','deleted')",
            name="ck_diagnosis_file_status",
        ),
        # 用户档案唯一性：同一用户同一标的只能有一个活跃档案
        Index(
            "uq_diagnosis_file_active",
            "user_id",
            "instrument_canonical_symbol",
            unique=True,
            postgresql_where="status = 'active' AND deleted_at IS NULL",
        ),
        # 用户历史索引
        Index(
            "ix_diagnosis_file_owner_history",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 标的信息（冗余存储，便于查询）
    instrument_canonical_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_market: Mapped[str] = mapped_column(String(4), nullable=False)
    instrument_exchange: Mapped[str | None] = mapped_column(String(16))
    instrument_display_name: Mapped[str | None] = mapped_column(String(128))
    instrument_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    instrument_timezone: Mapped[str] = mapped_column(String(32), nullable=False, default="UTC")
    instrument_original_input: Mapped[str | None] = mapped_column(String(128))
    instrument_normalization_method: Mapped[str | None] = mapped_column(String(32))
    instrument_ambiguity_resolved: Mapped[bool] = mapped_column(nullable=False, default=False)
    instrument_candidates: Mapped[list | None] = mapped_column(JSONB)

    # 状态
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )

    # 关联当前版本（延迟添加外键，因为 DiagnosisVersion 可能还不存在）
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True
    )

    # 扩展字段
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    # 时间戳
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class DiagnosisVersion(Base):
    """
    不可变诊断版本

    创建后不可修改；修正也产生新版本并标记原因。
    """
    __tablename__ = "diagnosis_versions"
    __table_args__ = (
        UniqueConstraint(
            "id", "diagnosis_file_id", name="uq_diagnosis_version_id_file"
        ),
        ForeignKeyConstraint(
            ["parent_version_id", "diagnosis_file_id"],
            ["diagnosis_versions.id", "diagnosis_versions.diagnosis_file_id"],
            name="fk_diagnosis_version_parent_file",
            ondelete="SET NULL (parent_version_id)",
            use_alter=True,
        ),
        # 同一档案版本号唯一
        Index(
            "uq_diagnosis_version_number",
            "diagnosis_file_id",
            "version_number",
            unique=True,
        ),
        # 版本指纹索引
        Index(
            "ix_diagnosis_version_fingerprint",
            "analysis_version",
        ),
        # 外键约束：diagnosis_file_id 必须存在
        # 注意：外键在迁移中添加，因为存在循环依赖
        # 检查约束
        CheckConstraint("version_number > 0", name="ck_version_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    diagnosis_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("diagnosis_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 版本指纹
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # 决策画像快照
    decision_profile_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 诊断证据（序列化的 EvidencePack）- 唯一不可变快照
    evidence_pack: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 维度意见
    dimension_opinions: Mapped[dict | None] = mapped_column(JSONB)

    # 冲突复核
    conflict_review: Mapped[dict | None] = mapped_column(JSONB)

    # 风险约束
    risk_assessment: Mapped[dict | None] = mapped_column(JSONB)

    # 诊断建议
    diagnosis_advice: Mapped[dict | None] = mapped_column(JSONB)

    # 规则、模型、来源与成本
    provenance: Mapped[dict | None] = mapped_column(JSONB)

    # 创建信息
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="initial")
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # 时间戳
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DiagnosisRun(Base):
    """
    诊断运行任务

    收敛自 DeepAnalysisReport，复用认领、租约、心跳、重试和积分逻辑。
    成功后只提交一个新的 DiagnosisVersion。
    """
    __tablename__ = "diagnosis_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "diagnosis_file_id"],
            ["diagnosis_files.user_id", "diagnosis_files.id"],
            name="fk_diagnosis_run_owner_file",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["diagnosis_version_id", "diagnosis_file_id"],
            ["diagnosis_versions.id", "diagnosis_versions.diagnosis_file_id"],
            name="fk_diagnosis_run_version_file",
            ondelete="SET NULL (diagnosis_version_id)",
        ),
        # worker 认领索引
        Index(
            "ix_diagnosis_run_worker_claim",
            "next_retry_at",
            "created_at",
            postgresql_where="status IN ('pending','retry_wait')",
        ),
        # 失联检测索引
        Index(
            "ix_diagnosis_run_stale_running",
            "heartbeat_at",
            postgresql_where="status = 'running'",
        ),
        # 检查约束
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_progress_range"),
        CheckConstraint("attempt_count >= 0", name="ck_attempt_count_positive"),
        CheckConstraint("max_attempts > 0", name="ck_max_attempts_positive"),
        CheckConstraint("lease_version >= 0", name="ck_lease_version_positive"),
        CheckConstraint("reserved_credits >= 0", name="ck_reserved_credits_positive"),
        CheckConstraint("settled_credits >= 0", name="ck_settled_credits_positive"),
        CheckConstraint(
            "status IN ('pending','running','retry_wait','completed','failed','cancelled')",
            name="ck_diagnosis_run_status",
        ),
        CheckConstraint(
            "credit_state IN ('reserved','settled','released')",
            name="ck_diagnosis_run_credit_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # 关联诊断档案
    diagnosis_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # 关联成功版本
    diagnosis_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True
    )

    # 任务状态机
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)

    # 执行租约
    worker_id: Mapped[str | None] = mapped_column(String(128))
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 输入快照
    instrument_data: Mapped[dict | None] = mapped_column(JSONB)
    decision_profile: Mapped[dict | None] = mapped_column(JSONB)

    # 注意：evidence_pack_id 已删除
    # Provider attempts 保留在 EvidencePack JSON 中，不单独存储

    # 错误
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    # 时间戳
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # 积分
    credit_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="reserved"
    )
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settled_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

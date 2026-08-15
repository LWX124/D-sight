"""
Diagnosis Schemas

公开 API 契约，定义请求和响应的数据结构。
与 docs/stock-diagnosis-design-plan.md 第 5 节核心契约对齐。
"""

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PositionType(str, Enum):
    """持仓状态"""
    EMPTY = "empty"      # 空仓：允许 buy / watch / avoid
    HOLDING = "holding"  # 持仓：允许 add / hold / reduce / sell


class InvestmentHorizon(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class RiskTolerance(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class DiagnosisFileStatus(str, Enum):
    active = "active"
    archived = "archived"
    deleted = "deleted"


class DiagnosisRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    retry_wait = "retry_wait"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class InstrumentSchema(BaseModel):
    """标的规范化信息"""
    market: Literal["CN", "US", "HK", "JP", "KR"] = Field(
        ..., description="市场代码 (CN/US/HK/JP/KR)"
    )
    canonical_symbol: str = Field(..., description="规范化标的代码")
    exchange: Optional[str] = Field(None, description="已验证的交易所；未知时为空")
    display_name: Optional[str] = Field(None, description="显示名称")
    currency: str = Field("USD", description="货币")
    timezone: str = Field("UTC", description="时区")
    # 规范化溯源
    original_input: Optional[str] = Field(None, description="用户原始输入")
    normalization_method: Optional[str] = Field(None, description="使用的规范化方法 (code_pattern/ticker_pattern/name_lookup)")
    ambiguity_resolved: bool = Field(False, description="是否已解决名称歧义")
    candidates: Optional[list[str]] = Field(None, description="歧义候选列表")


class DecisionProfileSchema(BaseModel):
    """
    决策画像快照

    创建诊断版本时冻结，同一版本中所有维度共享此画像。
    不同版本可以有不同的画像（用户主动调整或系统规则触发）。
    """
    position_status: PositionType = Field(PositionType.EMPTY, description="持仓状态 (empty/holding)")
    primary_horizon: InvestmentHorizon = Field(
        InvestmentHorizon.MEDIUM, description="主周期 (short/medium/long)"
    )
    risk_tolerance: RiskTolerance = Field(
        RiskTolerance.MODERATE,
        description="风险偏好 (conservative/moderate/aggressive)",
    )

    # 持仓上下文（position_status=HOLDING 时必需）
    portfolio_weight: Optional[float] = Field(None, ge=0.0, le=1.0, description="占组合比例，0.0-1.0")
    target_position_weight: Optional[float] = Field(None, ge=0.0, le=1.0, description="目标仓位权重，0.0-1.0")
    max_position_weight: Optional[float] = Field(None, ge=0.0, le=1.0, description="最大仓位权重，0.0-1.0")
    cost_basis: Optional[float] = Field(None, gt=0, description="持仓均价")
    entry_date: Optional[date] = Field(None, description="建仓日期")

    # 用户约束
    tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="用户标签（如 '核心仓位''观察仓'）",
    )

    # 快照溯源
    changed_from: Optional[str] = Field(None, description="上一个 profile_id")
    change_reason: Optional[str] = Field(None, description="变更原因")

    @model_validator(mode="after")
    def validate_position_context(self):
        holding_only = {
            "portfolio_weight": self.portfolio_weight,
            "cost_basis": self.cost_basis,
            "entry_date": self.entry_date,
        }
        if self.position_status is PositionType.HOLDING and self.portfolio_weight is None:
            raise ValueError("portfolio_weight is required for a holding position")
        if self.position_status is PositionType.EMPTY:
            supplied = [name for name, value in holding_only.items() if value is not None]
            if supplied:
                raise ValueError(
                    f"empty positions cannot include holding-only fields: {', '.join(supplied)}"
                )
        if (
            self.target_position_weight is not None
            and self.max_position_weight is not None
            and self.target_position_weight > self.max_position_weight
        ):
            raise ValueError("target_position_weight cannot exceed max_position_weight")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "position_status": "empty",
                    "primary_horizon": "medium",
                    "risk_tolerance": "moderate",
                    "tags": ["观察仓"],
                },
                {
                    "position_status": "holding",
                    "primary_horizon": "long",
                    "risk_tolerance": "conservative",
                    "portfolio_weight": 0.15,
                    "target_position_weight": 0.20,
                    "max_position_weight": 0.25,
                    "cost_basis": 1800.0,
                    "entry_date": "2026-01-15",
                    "tags": ["核心仓位"],
                },
            ]
        }
    )


class DimensionOpinionSchema(BaseModel):
    """Validated persistence/API boundary for a dimension opinion."""

    dimension_id: str
    horizon: InvestmentHorizon
    status: Literal["success", "degraded", "unavailable", "failed"]
    direction: Optional[Literal["bullish", "neutral", "bearish"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    thesis: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analyzer_version: str

    @model_validator(mode="after")
    def validate_status_contract(self):
        if self.status in {"success", "degraded"} and self.direction is None:
            raise ValueError(f"{self.status} opinions require a direction")
        if self.status in {"unavailable", "failed"} and self.direction is not None:
            raise ValueError(f"{self.status} opinions cannot vote on direction")
        if self.status == "degraded" and not self.warnings:
            raise ValueError("degraded opinions require at least one warning")
        return self


class DiagnosisFileCreateRequest(BaseModel):
    """创建诊断档案请求"""
    symbol: str = Field(..., description="股票代码或名称")
    market_hint: Optional[Literal["CN", "US", "HK", "JP", "KR"]] = Field(
        None, description="市场提示 (CN/US/HK/JP/KR)"
    )


class DiagnosisFileResponse(BaseModel):
    """诊断档案响应"""
    id: str = Field(..., description="档案 ID")
    instrument: InstrumentSchema = Field(..., description="标的规范化信息")
    status: DiagnosisFileStatus = Field(..., description="档案状态")
    current_version_id: Optional[str] = Field(None, description="当前版本 ID")
    version_count: int = Field(0, ge=0, description="版本数量")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class DiagnosisVersionResponse(BaseModel):
    """诊断版本响应"""
    id: str = Field(..., description="版本 ID")
    version_number: int = Field(..., gt=0, description="版本序号")
    analysis_version: str = Field(..., description="版本指纹")
    decision_profile: DecisionProfileSchema = Field(..., description="决策画像快照")
    diagnosis_advice: Optional[dict] = Field(None, description="诊断建议")
    reason: str = Field(..., description="创建原因")
    created_at: datetime = Field(..., description="创建时间")


class DiagnosisRunCreateRequest(BaseModel):
    """创建诊断运行请求"""
    decision_profile: Optional[DecisionProfileSchema] = Field(None, description="决策画像")


class DiagnosisRunResponse(BaseModel):
    """诊断运行响应"""
    id: str = Field(..., description="运行 ID")
    status: DiagnosisRunStatus = Field(..., description="运行状态")
    stage: str = Field(..., description="当前阶段")
    progress: int = Field(0, ge=0, le=100, description="进度百分比")
    diagnosis_version_id: Optional[str] = Field(None, description="成功版本 ID")
    error_message: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    finished_at: Optional[datetime] = Field(None, description="完成时间")


class DiagnosisVersionDiffResponse(BaseModel):
    """版本差异响应"""
    version_a: str = Field(..., description="版本 A ID")
    version_b: str = Field(..., description="版本 B ID")
    evidence_changes: list[dict] = Field(default_factory=list, description="证据变化")
    profile_changes: list[dict] = Field(default_factory=list, description="画像变化")
    method_changes: list[dict] = Field(default_factory=list, description="方法变化")
    advice_changes: list[dict] = Field(default_factory=list, description="建议变化")


class QualityGateResultSchema(BaseModel):
    """质量门禁结果"""
    passed: bool = Field(..., description="是否通过")
    availability: Literal["actionable", "limited", "insufficient"] = Field(
        ..., description="可用性 (actionable/limited/insufficient)"
    )
    quality_score: float = Field(..., ge=0.0, le=1.0, description="质量分数")
    completeness: float = Field(..., ge=0.0, le=1.0, description="完整性分数")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    warnings: list[str] = Field(default_factory=list, description="警告列表")

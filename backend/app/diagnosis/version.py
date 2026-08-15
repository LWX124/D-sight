"""
Version Identity & Immutability

版本身份生成和不可变性控制。
"""

import hashlib
import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from .evidence.schemas import EvidencePack
from .schemas import DecisionProfileSchema


@dataclass
class AnalysisManifest:
    """
    分析方法身份契约

    定义诊断方法的完整版本信息，用于版本指纹生成。
    """
    schema_version: str
    normalization_version: str
    indicator_registry_version: str
    dimension_registry_version: str
    prompt_version: str
    model_contract_version: str
    conflict_rules_version: str
    quality_rules_version: str
    risk_rules_version: str
    action_mapping_version: str

    def __post_init__(self) -> None:
        blank = [
            name
            for name, value in self.to_dict().items()
            if not isinstance(value, str) or not value.strip()
        ]
        if blank:
            raise ValueError(
                f"AnalysisManifest versions must be non-empty: {', '.join(blank)}"
            )

    def to_dict(self) -> dict:
        return {
            'schema_version': self.schema_version,
            'normalization_version': self.normalization_version,
            'indicator_registry_version': self.indicator_registry_version,
            'dimension_registry_version': self.dimension_registry_version,
            'prompt_version': self.prompt_version,
            'model_contract_version': self.model_contract_version,
            'conflict_rules_version': self.conflict_rules_version,
            'quality_rules_version': self.quality_rules_version,
            'risk_rules_version': self.risk_rules_version,
            'action_mapping_version': self.action_mapping_version,
        }


@dataclass
class ExecutionProvenance:
    """
    执行溯源

    记录实际执行的模型、端点、参数等信息。
    """
    actual_model_id: str
    endpoint: Optional[str] = None
    parameters: dict = field(default_factory=dict)
    actual_providers: dict[str, str] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'actual_model_id': self.actual_model_id,
            'endpoint': self.endpoint,
            'parameters': self.parameters,
            'actual_providers': self.actual_providers,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }


def hash_evidence_pack(pack: EvidencePack) -> str:
    """
    对 EvidencePack 生成哈希

    用于版本指纹生成。
    """
    data = {
        'schema_version': pack.schema_version,
        'instrument': pack.instrument.to_dict() if pack.instrument else None,
        'blocks': {
            block_id: {
                'items': {
                    item_id: _semantic_evidence_item(item)
                    for item_id, item in block.items.items()
                }
            }
            for block_id, block in pack.blocks.items()
        },
        'as_of': pack.as_of.isoformat() if pack.as_of else None,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()


def _semantic_evidence_item(item) -> dict:
    """Return every semantic EvidenceItem field, excluding collection time."""
    return {
        'evidence_id': item.evidence_id,
        'status': item.status.value,
        'value': item.value,
        'source': item.source,
        'source_record_id': item.source_record_id,
        'as_of': item.as_of.isoformat() if item.as_of else None,
        'currency': item.currency,
        'unit': item.unit,
        'period': item.period,
        'fallback_from': item.fallback_from,
        'missing_reason': item.missing_reason,
        'warnings': item.warnings,
    }


def hash_decision_profile(profile: DecisionProfileSchema) -> str:
    """
    对 DecisionProfileSnapshot 生成哈希

    用于版本指纹生成。
    """
    data = profile.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()


def generate_analysis_version(manifest: AnalysisManifest) -> str:
    """
    生成版本身份指纹

    由以下内容生成稳定指纹：
    - EvidencePack Schema 版本
    - provider 规范化规则
    - 确定性指标版本
    - 维度注册表和权重
    - prompt 版本和实际模型 ID
    - 冲突检测规则
    - 数据质量门槛
    - 风险规则
    - 动作映射规则

    只修改可读标签不能复用旧缓存；任何实际规则变化必须得到新版本指纹。
    """
    return hashlib.sha256(
        json.dumps(manifest.to_dict(), sort_keys=True).encode()
    ).hexdigest()


def generate_result_identity(
    manifest: AnalysisManifest,
    evidence_pack: EvidencePack,
    decision_profile: DecisionProfileSchema,
    freshness_policy: str,
) -> str:
    """Build a cache/result identity from explicit independent factors."""
    identity = {
        "analysis_version": generate_analysis_version(manifest),
        "evidence_hash": hash_evidence_pack(evidence_pack),
        "profile_hash": hash_decision_profile(decision_profile),
        "freshness_policy": freshness_policy,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


class ImmutabilityGuard:
    """
    不可变性守卫

    确保 DiagnosisVersion 创建后不可修改。
    """

    @staticmethod
    def validate_create(
        existing_versions: list[dict],
        new_version: dict,
    ) -> tuple[bool, str]:
        """
        验证创建新版本的合法性

        Args:
            existing_versions: 已有版本列表
            new_version: 新版本数据

        Returns:
            (is_valid, error_message)
        """
        # 检查版本号唯一性
        file_id = new_version.get('diagnosis_file_id')
        version_number = new_version.get('version_number')

        for v in existing_versions:
            if v.get('diagnosis_file_id') == file_id and v.get('version_number') == version_number:
                return False, f"Version number {version_number} already exists"

        return True, ""

    @staticmethod
    def validate_modify(
        existing_version: dict,
        modifications: dict,
    ) -> tuple[bool, str]:
        """
        验证修改已有版本的合法性

        不可变版本不允许修改，只能创建新版本。
        """
        return False, "DiagnosisVersion is immutable; create a new version instead"

    @staticmethod
    def validate_delete(
        existing_version: dict,
        user_id: str,
    ) -> tuple[bool, str]:
        """
        验证删除版本的合法性

        软删除：设置 deleted_at，不物理删除。
        """
        # 检查所有权
        if existing_version.get('created_by') != user_id:
            return False, "Not authorized to delete this version"

        return True, ""


def validate_version_immutability(
    existing_versions: list[dict],
    new_version: dict,
    user_id: str,
    modifications: Optional[dict] = None,
) -> tuple[bool, str]:
    """
    验证版本不可变性

    Args:
        existing_versions: 已有版本列表
        new_version: 新版本数据（创建时）或已有版本（修改/删除时）
        user_id: 用户 ID
        modifications: 修改数据（仅修改时）

    Returns:
        (is_valid, error_message)
    """
    guard = ImmutabilityGuard()

    if modifications is None:
        # 创建新版本
        return guard.validate_create(existing_versions, new_version)
    else:
        # 修改已有版本
        return guard.validate_modify(new_version, modifications)

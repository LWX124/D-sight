"""
Indicator Base Class

指标计算基类，所有确定性指标继承此类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from ..evidence.schemas import EvidencePack, EvidenceStatus


@dataclass
class IndicatorResult:
    """指标计算结果"""
    indicator_id: str
    value: Optional[float] = None
    status: EvidenceStatus = EvidenceStatus.missing
    source: str = ""
    as_of: Optional[datetime] = None
    unit: Optional[str] = None
    period: Optional[str] = None
    confidence: float = 0.0  # 计算确定性，非预测准确率
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'indicator_id': self.indicator_id,
            'value': self.value,
            'status': self.status.value,
            'source': self.source,
            'as_of': self.as_of.isoformat() if self.as_of else None,
            'unit': self.unit,
            'period': self.period,
            'confidence': self.confidence,
            'warnings': self.warnings,
        }


class IndicatorCalculator(ABC):
    """指标计算器基类"""
    category: str = ""  # financial / valuation / technical / risk

    @abstractmethod
    def calculate(
        self,
        evidence_pack: EvidencePack,
    ) -> dict[str, IndicatorResult]:
        """
        计算该类别的所有指标

        Args:
            evidence_pack: 证据包

        Returns:
            指标结果字典，key 为 indicator_id
        """
        pass

    def _get_evidence_value(
        self,
        evidence_pack: EvidencePack,
        evidence_id: str,
    ) -> Optional[Any]:
        """获取证据值"""
        item = evidence_pack.get_item(evidence_id)
        if item and item.status == EvidenceStatus.available:
            return item.value
        return None

    def _get_evidence_float(
        self,
        evidence_pack: EvidencePack,
        evidence_id: str,
    ) -> Optional[float]:
        """获取证据浮点值"""
        val = self._get_evidence_value(evidence_pack, evidence_id)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        return None

    def _safe_divide(
        self,
        numerator: Optional[float],
        denominator: Optional[float],
    ) -> Optional[float]:
        """安全除法"""
        if numerator is None or denominator is None:
            return None
        if denominator == 0:
            return None
        return numerator / denominator

    def _safe_growth_rate(
        self,
        current: Optional[float],
        previous: Optional[float],
    ) -> Optional[float]:
        """计算增长率"""
        if current is None or previous is None:
            return None
        if previous == 0:
            return None
        return (current - previous) / abs(previous)

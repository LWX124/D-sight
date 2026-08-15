"""
Dimension Base Class

维度意见生成基类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from ..evidence.schemas import EvidencePack, Horizon


@dataclass
class DimensionOpinion:
    """维度意见"""
    dimension_id: str
    horizon: Horizon
    status: Literal["success", "degraded", "unavailable", "failed"]
    direction: Optional[Literal["bullish", "neutral", "bearish"]]
    confidence: Optional[float] = None  # 维度内部证据一致性，0.0-1.0
    thesis: Optional[str] = None
    evidence_ids: list[str] = field(default_factory=list)
    missing_evidence_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analyzer_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.status in {"success", "degraded"} and self.direction is None:
            raise ValueError(f"{self.status} opinions require a direction")
        if self.status in {"unavailable", "failed"} and self.direction is not None:
            raise ValueError(f"{self.status} opinions cannot vote on direction")
        if self.status == "degraded" and not self.warnings:
            raise ValueError("degraded opinions require at least one warning")

    def to_dict(self) -> dict:
        return {
            'dimension_id': self.dimension_id,
            'horizon': self.horizon.value,
            'status': self.status,
            'direction': self.direction,
            'confidence': self.confidence,
            'thesis': self.thesis,
            'evidence_ids': self.evidence_ids,
            'missing_evidence_ids': self.missing_evidence_ids,
            'warnings': self.warnings,
            'analyzer_version': self.analyzer_version,
        }


class DimensionAnalyzer(ABC):
    """维度分析器基类"""
    dimension_id: str = ""
    required_evidence: list[str] = []

    @abstractmethod
    def analyze(
        self,
        evidence_pack: EvidencePack,
        indicators: dict,
        horizon: Horizon,
    ) -> DimensionOpinion:
        """生成维度意见"""
        pass

    def _check_evidence(self, evidence_pack: EvidencePack) -> tuple[list[str], list[str]]:
        """检查证据完整性，返回 (available_ids, missing_ids)"""
        available = []
        missing = []
        for eid in self.required_evidence:
            item = evidence_pack.get_item(eid)
            if item and item.status.value in ('available', 'partial', 'fallback'):
                available.append(eid)
            else:
                missing.append(eid)
        return available, missing

    def _calculate_confidence(self, available: int, total: int) -> float:
        """基于证据完整性计算置信度"""
        if total == 0:
            return 0.0
        return min(available / total, 1.0)

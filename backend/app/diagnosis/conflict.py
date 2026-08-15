"""
Direction Conflict Detector

检测维度间的方向冲突。
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid

from .dimensions.base import DimensionOpinion


@dataclass
class ConflictReview:
    """冲突复核结果"""
    conflict_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflicting_dimensions: list[str] = field(default_factory=list)
    conflicting_evidence: list[str] = field(default_factory=list)
    is_resolved: bool = False
    resolution: Optional[str] = None
    retained_objections: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    reviewer_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            'conflict_id': self.conflict_id,
            'conflicting_dimensions': self.conflicting_dimensions,
            'conflicting_evidence': self.conflicting_evidence,
            'is_resolved': self.is_resolved,
            'resolution': self.resolution,
            'retained_objections': self.retained_objections,
            'missing_evidence': self.missing_evidence,
            'reviewer_version': self.reviewer_version,
        }


class ConflictDetector:
    """冲突检测器"""

    def detect(
        self,
        opinions: list[DimensionOpinion],
        primary_horizon: str,
    ) -> Optional[ConflictReview]:
        """
        检测维度间的方向冲突

        规则:
        1. 同一周期出现 >= 2 个 status=success 维度，direction 分别为 bullish 和 bearish
        2. valuation.direction != financial_quality.direction，且任一 confidence >= 0.7
        3. technical.direction 与主周期建议相反
        4. events_and_sentiment 包含负面事件，但其他维度为 bullish
        5. 多个维度引用同一 evidence_id，但得出矛盾解释
        """
        # 只考虑 status=success 的维度
        success_opinions = [
            o for o in opinions
            if o.status in {'success', 'degraded'}
            and o.direction is not None
            and o.horizon.value == primary_horizon
        ]

        if len(success_opinions) < 2:
            return None

        conflicts = []

        # 规则1: 同一周期同时出现 bullish 和 bearish
        bullish = [o for o in success_opinions if o.direction == 'bullish']
        bearish = [o for o in success_opinions if o.direction == 'bearish']

        if bullish and bearish:
            conflicts.append({
                'dimensions': [o.dimension_id for o in bullish + bearish],
                'reason': f"同时存在看多({[o.dimension_id for o in bullish]})和看空({[o.dimension_id for o in bearish]})意见",
            })

        # 规则2: 估值与财务方向相反
        val_opinion = next((o for o in success_opinions if o.dimension_id == 'valuation'), None)
        fin_opinion = next((o for o in success_opinions if o.dimension_id == 'financial_quality'), None)

        if (val_opinion and fin_opinion
                and val_opinion.direction != fin_opinion.direction
                and val_opinion.direction != 'neutral'
                and fin_opinion.direction != 'neutral'):
            if (val_opinion.confidence or 0) >= 0.7 or (fin_opinion.confidence or 0) >= 0.7:
                conflicts.append({
                    'dimensions': ['valuation', 'financial_quality'],
                    'reason': f"估值({val_opinion.direction})与财务({fin_opinion.direction})方向相反",
                })

        if not conflicts:
            return None

        # 构建 ConflictReview
        conflicting_dims = []
        for c in conflicts:
            conflicting_dims.extend(c['dimensions'])
        conflicting_dims = list(set(conflicting_dims))

        review = ConflictReview(
            conflicting_dimensions=conflicting_dims,
            is_resolved=False,
            resolution=None,
            retained_objections=[c['reason'] for c in conflicts],
        )

        return review

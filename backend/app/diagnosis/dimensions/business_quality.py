"""
Business Quality Dimension

商业质量与竞争优势维度。
"""

from ..evidence.schemas import EvidencePack, Horizon
from .base import DimensionAnalyzer, DimensionOpinion


class BusinessQualityAnalyzer(DimensionAnalyzer):
    """商业质量分析器"""
    dimension_id = "business_quality"
    required_evidence = [
        'identity_name', 'identity_sector', 'identity_industry',
        'fundamentals_roe', 'fundamentals_revenue_growth',
        'ownership_major_holders',
    ]

    def analyze(self, evidence_pack: EvidencePack, indicators: dict, horizon: Horizon) -> DimensionOpinion:
        available, missing = self._check_evidence(evidence_pack)
        confidence = self._calculate_confidence(len(available), len(self.required_evidence))

        if confidence < 0.3:
            return DimensionOpinion(
                dimension_id=self.dimension_id,
                horizon=horizon,
                status='unavailable',
                direction=None,
                confidence=confidence,
                thesis='证据不足，无法评估商业质量',
                evidence_ids=available,
                missing_evidence_ids=missing,
            )

        # 基于 ROE 和营收增长判断方向
        roe_ind = indicators.get('roe')
        growth_ind = indicators.get('revenue_growth_rate')

        direction = 'neutral'
        thesis_parts = []

        if roe_ind and roe_ind.value is not None:
            if roe_ind.value > 0.15:
                direction = 'bullish'
                thesis_parts.append(f"ROE {roe_ind.value:.1%} 较高，盈利能力强")
            elif roe_ind.value < 0.05:
                direction = 'bearish'
                thesis_parts.append(f"ROE {roe_ind.value:.1%} 较低，盈利能力弱")

        if growth_ind and growth_ind.value is not None:
            if growth_ind.value > 0.1:
                if direction != 'bearish':
                    direction = 'bullish'
                thesis_parts.append(f"营收增长 {growth_ind.value:.1%}")
            elif growth_ind.value < -0.1:
                if direction != 'bullish':
                    direction = 'bearish'
                thesis_parts.append(f"营收下滑 {growth_ind.value:.1%}")

        thesis = '；'.join(thesis_parts) if thesis_parts else '商业质量指标中性'

        return DimensionOpinion(
            dimension_id=self.dimension_id,
            horizon=horizon,
            status='success' if confidence >= 0.6 else 'degraded',
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            evidence_ids=available,
            missing_evidence_ids=missing,
            warnings=['部分商业质量证据缺失'] if confidence < 0.6 else [],
        )

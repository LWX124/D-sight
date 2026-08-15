"""
Financial Quality Dimension

财务质量维度：增长、盈利、现金流、资产负债与资本配置。
"""

from ..evidence.schemas import EvidencePack, Horizon
from .base import DimensionAnalyzer, DimensionOpinion


class FinancialQualityAnalyzer(DimensionAnalyzer):
    """财务质量分析器"""
    dimension_id = "financial_quality"
    required_evidence = [
        'fundamentals_revenue', 'fundamentals_net_income',
        'fundamentals_operating_cash_flow', 'fundamentals_total_debt',
        'fundamentals_total_assets',
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
                thesis='财务数据不足',
                evidence_ids=available,
                missing_evidence_ids=missing,
            )

        direction = 'neutral'
        thesis_parts = []

        # ROE
        roe = indicators.get('roe')
        if roe and roe.value is not None:
            if roe.value > 0.15:
                direction = 'bullish'
                thesis_parts.append(f"ROE {roe.value:.1%}")
            elif roe.value < 0.05:
                direction = 'bearish'
                thesis_parts.append(f"ROE {roe.value:.1%} 偏低")

        # 负债率
        debt = indicators.get('debt_ratio')
        if debt and debt.value is not None:
            if debt.value > 0.7:
                if direction != 'bullish':
                    direction = 'bearish'
                thesis_parts.append(f"负债率 {debt.value:.1%} 较高")
            elif debt.value < 0.3:
                thesis_parts.append(f"负债率 {debt.value:.1%} 健康")

        # 现金流
        cf = indicators.get('cash_flow_to_profit')
        if cf and cf.value is not None:
            if cf.value > 1.0:
                thesis_parts.append("现金流充裕")
            elif cf.value < 0.5:
                if direction != 'bullish':
                    direction = 'bearish'
                thesis_parts.append("现金流偏弱")

        thesis = '；'.join(thesis_parts) if thesis_parts else '财务指标中性'

        return DimensionOpinion(
            dimension_id=self.dimension_id,
            horizon=horizon,
            status='success' if confidence >= 0.6 else 'degraded',
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            evidence_ids=available,
            missing_evidence_ids=missing,
            warnings=['部分财务证据缺失'] if confidence < 0.6 else [],
        )

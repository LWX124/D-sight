"""
Market Structure Dimension

市场结构维度：市场阶段、行业/主题位置和宏观环境。
"""

from ..evidence.schemas import EvidencePack, Horizon
from .base import DimensionAnalyzer, DimensionOpinion


class MarketStructureAnalyzer(DimensionAnalyzer):
    """市场结构分析器"""
    dimension_id = "market_structure"
    required_evidence = [
        'market_context_sector_performance', 'market_context_market_phase',
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
                thesis='市场数据不足',
                evidence_ids=available,
                missing_evidence_ids=missing,
            )

        direction = 'neutral'
        thesis_parts = []

        # 市场阶段
        phase = evidence_pack.get_item('market_context_market_phase')
        if phase and phase.value is not None:
            phase_val = str(phase.value).lower()
            if 'bull' in phase_val or 'uptrend' in phase_val:
                direction = 'bullish'
                thesis_parts.append("市场处于上升趋势")
            elif 'bear' in phase_val or 'downtrend' in phase_val:
                direction = 'bearish'
                thesis_parts.append("市场处于下降趋势")
            else:
                thesis_parts.append(f"市场阶段: {phase.value}")

        # 行业表现
        sector = evidence_pack.get_item('market_context_sector_performance')
        if sector and sector.value is not None:
            try:
                perf = float(sector.value)
                if perf > 0.05:
                    thesis_parts.append(f"行业表现强劲 ({perf:.1%})")
                elif perf < -0.05:
                    thesis_parts.append(f"行业表现疲弱 ({perf:.1%})")
            except (ValueError, TypeError):
                pass

        thesis = '；'.join(thesis_parts) if thesis_parts else '市场结构中性'

        return DimensionOpinion(
            dimension_id=self.dimension_id,
            horizon=horizon,
            status='success' if confidence >= 0.6 else 'degraded',
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            evidence_ids=available,
            missing_evidence_ids=missing,
            warnings=['部分市场结构证据缺失'] if confidence < 0.6 else [],
        )

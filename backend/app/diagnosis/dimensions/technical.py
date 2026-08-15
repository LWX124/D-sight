"""
Technical Dimension

技术维度：趋势、量价、波动和关键价格区间。
"""

from ..evidence.schemas import EvidencePack, Horizon
from .base import DimensionAnalyzer, DimensionOpinion


class TechnicalAnalyzer(DimensionAnalyzer):
    """技术分析器"""
    dimension_id = "technical"
    required_evidence = [
        'quote_price', 'technical_sma_20', 'technical_sma_50',
        'technical_rsi_14', 'technical_macd',
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
                thesis='技术数据不足',
                evidence_ids=available,
                missing_evidence_ids=missing,
            )

        direction = 'neutral'
        thesis_parts = []

        # 均线排列
        ma_align = indicators.get('price_ma_alignment')
        if ma_align and ma_align.value is not None:
            if ma_align.value > 0:
                direction = 'bullish'
                thesis_parts.append("均线多头排列")
            elif ma_align.value < 0:
                direction = 'bearish'
                thesis_parts.append("均线空头排列")

        # RSI
        rsi = indicators.get('rsi_14')
        if rsi and rsi.value is not None:
            if rsi.value < 30:
                if direction != 'bearish':
                    direction = 'bullish'
                thesis_parts.append(f"RSI {rsi.value:.0f} 超卖")
            elif rsi.value > 70:
                if direction != 'bullish':
                    direction = 'bearish'
                thesis_parts.append(f"RSI {rsi.value:.0f} 超买")
            else:
                thesis_parts.append(f"RSI {rsi.value:.0f}")

        # MACD
        macd = indicators.get('macd')
        if macd and macd.value is not None:
            if macd.value > 0:
                thesis_parts.append("MACD 为正")
            else:
                thesis_parts.append("MACD 为负")

        thesis = '；'.join(thesis_parts) if thesis_parts else '技术面中性'

        return DimensionOpinion(
            dimension_id=self.dimension_id,
            horizon=horizon,
            status='success' if confidence >= 0.6 else 'degraded',
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            evidence_ids=available,
            missing_evidence_ids=missing,
            warnings=['部分技术证据缺失'] if confidence < 0.6 else [],
        )

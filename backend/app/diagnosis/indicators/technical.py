"""
Technical Indicators

确定性技术指标计算。
"""


from .base import IndicatorCalculator, IndicatorResult
from ..evidence.schemas import EvidencePack, EvidenceStatus


class TechnicalIndicatorCalculator(IndicatorCalculator):
    """技术指标计算器"""
    category = "technical"

    def calculate(self, evidence_pack: EvidencePack) -> dict[str, IndicatorResult]:
        results = {}

        results['sma_20'] = self._get_direct(evidence_pack, 'technical_sma_20', 'sma_20')
        results['sma_50'] = self._get_direct(evidence_pack, 'technical_sma_50', 'sma_50')
        results['sma_200'] = self._get_direct(evidence_pack, 'technical_sma_200', 'sma_200')
        results['macd'] = self._get_direct(evidence_pack, 'technical_macd', 'macd')
        results['rsi_14'] = self._get_direct(evidence_pack, 'technical_rsi_14', 'rsi_14')
        results['bollinger_upper'] = self._get_direct(evidence_pack, 'technical_bollinger_upper', 'bollinger_upper')
        results['bollinger_lower'] = self._get_direct(evidence_pack, 'technical_bollinger_lower', 'bollinger_lower')
        results['volume_trend'] = self._get_direct(evidence_pack, 'technical_volume_trend', 'volume_trend')

        # 价格与均线排列
        results['price_ma_alignment'] = self._calc_ma_alignment(evidence_pack)

        # 波动率（基于日线）
        results['volatility_20d'] = self._get_direct(evidence_pack, 'technical_volatility_20d', 'volatility_20d', unit='%')

        return results

    def _get_direct(self, pack: EvidencePack, evidence_id: str, indicator_id: str, unit: str = 'price') -> IndicatorResult:
        value = self._get_evidence_float(pack, evidence_id)
        item = pack.get_item(evidence_id)

        if value is None:
            return IndicatorResult(indicator_id=indicator_id, status=EvidenceStatus.missing)

        return IndicatorResult(
            indicator_id=indicator_id,
            value=round(value, 4),
            status=EvidenceStatus.available,
            source=item.source if item else '',
            as_of=item.as_of if item else None,
            unit=unit,
            confidence=0.95,
        )

    def _calc_ma_alignment(self, pack: EvidencePack) -> IndicatorResult:
        """计算价格与均线排列"""
        price = self._get_evidence_float(pack, 'quote_price')
        sma20 = self._get_evidence_float(pack, 'technical_sma_20')
        sma50 = self._get_evidence_float(pack, 'technical_sma_50')
        sma200 = self._get_evidence_float(pack, 'technical_sma_200')

        if any(v is None for v in [price, sma20, sma50, sma200]):
            return IndicatorResult(indicator_id='price_ma_alignment', status=EvidenceStatus.missing)

        # 多头排列: price > sma20 > sma50 > sma200
        if price > sma20 > sma50 > sma200:
            value = 1.0  # 多头
        elif price < sma20 < sma50 < sma200:
            value = -1.0  # 空头
        else:
            value = 0.0  # 混合

        return IndicatorResult(
            indicator_id='price_ma_alignment',
            value=value,
            status=EvidenceStatus.available,
            source='calculated',
            unit='alignment',
            confidence=0.9,
        )

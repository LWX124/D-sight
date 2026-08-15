"""
Risk Indicators

确定性风险指标计算。
"""

from .base import IndicatorCalculator, IndicatorResult
from ..evidence.schemas import EvidencePack, EvidenceStatus


class RiskIndicatorCalculator(IndicatorCalculator):
    """风险指标计算器"""
    category = "risk"

    def calculate(self, evidence_pack: EvidencePack) -> dict[str, IndicatorResult]:
        results = {}

        results['volatility_20d'] = self._get_direct(evidence_pack, 'risk_volatility_20d', 'volatility_20d', unit='%')
        results['volatility_60d'] = self._get_direct(evidence_pack, 'risk_volatility_60d', 'volatility_60d', unit='%')
        results['max_drawdown_60d'] = self._get_direct(evidence_pack, 'risk_max_drawdown_60d', 'max_drawdown_60d', unit='%')
        results['sharpe_ratio'] = self._get_direct(evidence_pack, 'risk_sharpe_ratio', 'sharpe_ratio')
        results['beta'] = self._get_direct(evidence_pack, 'risk_beta', 'beta')
        results['atr_14'] = self._get_direct(evidence_pack, 'risk_atr_14', 'atr_14', unit='price')

        return results

    def _get_direct(self, pack: EvidencePack, evidence_id: str, indicator_id: str, unit: str = 'ratio') -> IndicatorResult:
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

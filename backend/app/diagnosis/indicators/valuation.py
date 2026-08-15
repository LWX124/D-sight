"""
Valuation Indicators

确定性估值指标计算。
"""

from .base import IndicatorCalculator, IndicatorResult
from ..evidence.schemas import EvidencePack, EvidenceStatus


class ValuationIndicatorCalculator(IndicatorCalculator):
    """估值指标计算器"""
    category = "valuation"

    def calculate(self, evidence_pack: EvidencePack) -> dict[str, IndicatorResult]:
        results = {}

        results['pe_ratio'] = self._get_direct(evidence_pack, 'valuation_pe', 'pe_ratio', unit='x')
        results['pb_ratio'] = self._get_direct(evidence_pack, 'valuation_pb', 'pb_ratio', unit='x')
        results['ps_ratio'] = self._get_direct(evidence_pack, 'valuation_ps', 'ps_ratio', unit='x')
        results['ev_ebitda'] = self._get_direct(evidence_pack, 'valuation_ev_ebitda', 'ev_ebitda', unit='x')

        # 历史分位数
        results['pe_percentile'] = self._get_direct(evidence_pack, 'valuation_pe_percentile', 'pe_percentile', unit='%')
        results['pb_percentile'] = self._get_direct(evidence_pack, 'valuation_pb_percentile', 'pb_percentile', unit='%')

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

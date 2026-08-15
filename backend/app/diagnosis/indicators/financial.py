"""
Financial Indicators

确定性财务指标计算。
"""

from .base import IndicatorCalculator, IndicatorResult
from ..evidence.schemas import EvidencePack, EvidenceStatus


class FinancialIndicatorCalculator(IndicatorCalculator):
    """财务指标计算器"""
    category = "financial"

    def calculate(self, evidence_pack: EvidencePack) -> dict[str, IndicatorResult]:
        results = {}

        results['revenue_growth_rate'] = self._calc_growth_rate(
            evidence_pack, 'fundamentals_revenue_current', 'fundamentals_revenue_previous', 'revenue_growth_rate')

        results['net_profit_growth_rate'] = self._calc_growth_rate(
            evidence_pack, 'fundamentals_net_income_current', 'fundamentals_net_income_previous', 'net_profit_growth_rate')

        results['roe'] = self._calc_ratio(
            evidence_pack, 'fundamentals_net_income', 'fundamentals_shareholders_equity', 'roe')

        results['debt_ratio'] = self._calc_ratio(
            evidence_pack, 'fundamentals_total_debt', 'fundamentals_total_assets', 'debt_ratio')

        results['cash_flow_to_profit'] = self._calc_ratio(
            evidence_pack, 'fundamentals_operating_cash_flow', 'fundamentals_net_income', 'cash_flow_to_profit')

        results['gross_margin'] = self._calc_margin(
            evidence_pack, 'fundamentals_gross_profit', 'fundamentals_revenue', 'gross_margin')

        results['net_margin'] = self._calc_margin(
            evidence_pack, 'fundamentals_net_income', 'fundamentals_revenue', 'net_margin')

        return results

    def _calc_growth_rate(self, pack: EvidencePack, current_id: str, previous_id: str, indicator_id: str) -> IndicatorResult:
        current = self._get_evidence_float(pack, current_id)
        previous = self._get_evidence_float(pack, previous_id)
        value = self._safe_growth_rate(current, previous)

        if value is None:
            return IndicatorResult(indicator_id=indicator_id, status=EvidenceStatus.missing)

        return IndicatorResult(
            indicator_id=indicator_id,
            value=round(value, 4),
            status=EvidenceStatus.available,
            source=pack.get_item(current_id).source if pack.get_item(current_id) else '',
            as_of=pack.get_item(current_id).as_of if pack.get_item(current_id) else None,
            unit='ratio',
            confidence=0.95,
        )

    def _calc_ratio(self, pack: EvidencePack, numerator_id: str, denominator_id: str, indicator_id: str, unit: str = 'ratio') -> IndicatorResult:
        """相除得到的指标一律是比例（0.0969 = 9.69%），unit 必须如实写 'ratio'。
        曾经标成 '%' 却输出比例，掩盖了估值分位数那处真正的量纲错误。"""
        numerator = self._get_evidence_float(pack, numerator_id)
        denominator = self._get_evidence_float(pack, denominator_id)
        value = self._safe_divide(numerator, denominator)

        if value is None:
            return IndicatorResult(indicator_id=indicator_id, status=EvidenceStatus.missing)

        return IndicatorResult(
            indicator_id=indicator_id,
            value=round(value, 4),
            status=EvidenceStatus.available,
            source=pack.get_item(numerator_id).source if pack.get_item(numerator_id) else '',
            as_of=pack.get_item(numerator_id).as_of if pack.get_item(numerator_id) else None,
            unit=unit,
            confidence=0.95,
        )

    def _calc_margin(self, pack: EvidencePack, profit_id: str, revenue_id: str, indicator_id: str) -> IndicatorResult:
        return self._calc_ratio(pack, profit_id, revenue_id, indicator_id)

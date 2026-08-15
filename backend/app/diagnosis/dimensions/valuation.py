"""
Valuation Dimension

估值维度：估值区间与安全边际。
"""

from ..evidence.schemas import EvidencePack, Horizon
from .base import DimensionAnalyzer, DimensionOpinion

# 历史分位数由 marketdata 产出，量纲是 0–100 的百分数（19.75 表示 19.75%）。
CHEAP_PERCENTILE = 20.0
RICH_PERCENTILE = 80.0

# 无分位数时才用的绝对倍数。跨行业绝对倍数几乎没有可比性
# （银行 PB 0.6 与白酒 PB 6 都属正常），因此只作兜底且口径写进 thesis。
_CHEAP_PE = 15.0
_RICH_PE = 30.0


class ValuationAnalyzer(DimensionAnalyzer):
    """估值分析器"""
    dimension_id = "valuation"
    required_evidence = [
        'valuation_pe', 'valuation_pb', 'valuation_ps',
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
                thesis='估值数据不足',
                evidence_ids=available,
                missing_evidence_ids=missing,
            )

        thesis_parts: list[str] = []
        signals: list[str] = []

        for label, ratio_id, pct_id in (
            ('PE', 'pe_ratio', 'pe_percentile'),
            ('PB', 'pb_ratio', 'pb_percentile'),
        ):
            signal, text = self._judge(label, indicators.get(ratio_id), indicators.get(pct_id))
            if text:
                thesis_parts.append(text)
            if signal:
                signals.append(signal)

        # PE 与 PB 指向相反时不硬凑方向——两者矛盾本身就是"看不清"。
        direction = signals[0] if signals and len(set(signals)) == 1 else 'neutral'
        thesis = '；'.join(thesis_parts) if thesis_parts else '估值中性'

        return DimensionOpinion(
            dimension_id=self.dimension_id,
            horizon=horizon,
            status='success' if confidence >= 0.6 else 'degraded',
            direction=direction,
            confidence=confidence,
            thesis=thesis,
            evidence_ids=available,
            missing_evidence_ids=missing,
            warnings=['部分估值证据缺失'] if confidence < 0.6 else [],
        )

    @staticmethod
    def _judge(label: str, ratio, percentile) -> tuple[str | None, str | None]:
        """单个倍数的贵贱判断。

        以自身历史分位数为准：它天然按个股自己的历史归一，跨行业可比。
        只有拿不到分位数时才退回绝对倍数，并在结论里写明这是粗判。
        """
        if percentile is not None and percentile.value is not None:
            pct = float(percentile.value)
            if pct < CHEAP_PERCENTILE:
                return 'bullish', f"{label} 处于近 5 年 {pct:.1f}% 分位，历史低位"
            if pct > RICH_PERCENTILE:
                return 'bearish', f"{label} 处于近 5 年 {pct:.1f}% 分位，历史高位"
            return None, f"{label} 处于近 5 年 {pct:.1f}% 分位"

        if ratio is None or ratio.value is None:
            return None, None
        if label != 'PE':
            # PB 没有分位数时不给方向：绝对 PB 的高低完全取决于行业。
            return None, f"PB {ratio.value:.2f}（无历史分位，未据此判断）"

        value = float(ratio.value)
        if value < _CHEAP_PE:
            return 'bullish', f"PE {value:.1f}，低于绝对参考线 {_CHEAP_PE:.0f}（无历史分位，跨行业粗判）"
        if value > _RICH_PE:
            return 'bearish', f"PE {value:.1f}，高于绝对参考线 {_RICH_PE:.0f}（无历史分位，跨行业粗判）"
        return None, f"PE {value:.1f}（无历史分位）"

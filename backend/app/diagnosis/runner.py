"""
Diagnosis Runner

真实诊断 Runner，替换 Mock，形成 A 股和美股首个可执行闭环。
"""

import time
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field

from .evidence.schemas import EvidencePack, EvidenceStatus, Horizon
from .schemas import DecisionProfileSchema, PositionType
from .indicators.registry import calculate_all_indicators
from .dimensions.registry import analyze_all_dimensions
from .conflict import ConflictDetector, ConflictReview
from .dimensions.valuation import CHEAP_PERCENTILE
from .quality_gate import QualityGate, RiskConstraint
from .provenance import ProvenanceRecord

# 看多类动作等的是更好的买点，看空类动作等的是重新关注的理由。两类都必须给出
# 具体水位：一个「回避」若不说明何时该重新看，等于把股票扔掉，对决策没有价值。
BULLISH_ACTIONS = ('buy', 'add', 'watch', 'hold')
BEARISH_ACTIONS = ('avoid', 'reduce', 'sell')


@dataclass
class DiagnosisConclusion:
    """诊断结论"""
    horizon: Horizon
    action: str
    confidence: float
    triggering_conditions: list[str] = field(default_factory=list)
    invalidating_conditions: list[str] = field(default_factory=list)
    execution_adjustments: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'horizon': self.horizon.value,
            'action': self.action,
            'confidence': self.confidence,
            'triggering_conditions': self.triggering_conditions,
            'invalidating_conditions': self.invalidating_conditions,
            'execution_adjustments': self.execution_adjustments,
            'risk_reasons': self.risk_reasons,
        }


@dataclass
class DiagnosisAdvice:
    """诊断建议"""
    primary_horizon: Horizon
    conclusion: DiagnosisConclusion
    cross_horizon_analysis: Optional[str] = None
    overall_confidence: float = 0.0
    provenance: Optional[ProvenanceRecord] = None
    conflict_review: Optional[ConflictReview] = None

    def to_dict(self) -> dict:
        return {
            'primary_horizon': self.primary_horizon.value,
            'conclusion': self.conclusion.to_dict(),
            'cross_horizon_analysis': self.cross_horizon_analysis,
            'overall_confidence': self.overall_confidence,
            'provenance': self.provenance.to_dict() if self.provenance else None,
            'conflict_review': self.conflict_review.to_dict() if self.conflict_review else None,
        }


class DiagnosisRunner:
    """诊断 Runner"""

    def __init__(self):
        self.quality_gate = QualityGate()
        self.risk_constraint = RiskConstraint()
        self.conflict_detector = ConflictDetector()

    def run(
        self,
        evidence_pack: EvidencePack,
        decision_profile: DecisionProfileSchema,
    ) -> DiagnosisAdvice:
        """
        执行诊断

        Args:
            evidence_pack: 证据包
            decision_profile: 决策画像

        Returns:
            诊断建议
        """
        start_time = time.time()
        provenance = ProvenanceRecord(started_at=datetime.now(timezone.utc))

        # 1. 质量门禁
        quality_result = self.quality_gate.check(
            evidence_pack,
            evidence_pack.instrument.market.value if evidence_pack.instrument else 'unknown',
            decision_profile.primary_horizon.value,
        )

        if not quality_result.passed:
            # 数据不足，返回 insufficient
            conclusion = DiagnosisConclusion(
                horizon=Horizon(decision_profile.primary_horizon),
                action='watch' if decision_profile.position_status == PositionType.EMPTY else 'hold',
                confidence=0.1,
                risk_reasons=quality_result.errors,
            )
            provenance.finished_at = datetime.now(timezone.utc)
            provenance.total_latency_ms = (time.time() - start_time) * 1000
            return DiagnosisAdvice(
                primary_horizon=Horizon(decision_profile.primary_horizon),
                conclusion=conclusion,
                overall_confidence=0.1,
                provenance=provenance,
            )

        # 2. 计算确定性指标
        indicator_start = time.time()
        indicators = calculate_all_indicators(evidence_pack)
        provenance.indicator_latency_ms = (time.time() - indicator_start) * 1000

        # 3. 六维度意见
        dimension_start = time.time()
        horizon = Horizon(decision_profile.primary_horizon)
        opinions = analyze_all_dimensions(evidence_pack, indicators, horizon)
        provenance.dimension_latency_ms = (time.time() - dimension_start) * 1000

        # 4. 冲突检测
        conflict_review = self.conflict_detector.detect(opinions, decision_profile.primary_horizon)

        # 5. 确定动作
        direction = self._aggregate_direction(opinions)
        action = self._determine_action(direction, decision_profile)
        action = self.risk_constraint.apply_constraints(action, decision_profile, indicators)

        # 6. 置信度
        success_opinions = [o for o in opinions if o.status == 'success']
        avg_confidence = (
            sum(o.confidence or 0 for o in success_opinions) / len(success_opinions)
            if success_opinions else 0.1
        )

        # 7. 结论
        conclusion = DiagnosisConclusion(
            horizon=horizon,
            action=action,
            confidence=avg_confidence,
            triggering_conditions=self._get_triggering_conditions(
                action, indicators, evidence_pack
            ),
            invalidating_conditions=self._get_invalidating_conditions(
                action, indicators, evidence_pack
            ),
            risk_reasons=[],
        )

        provenance.finished_at = datetime.now(timezone.utc)
        provenance.total_latency_ms = (time.time() - start_time) * 1000

        return DiagnosisAdvice(
            primary_horizon=horizon,
            conclusion=conclusion,
            overall_confidence=avg_confidence,
            provenance=provenance,
            conflict_review=conflict_review,
        )

    def _aggregate_direction(self, opinions: list) -> str:
        """聚合维度方向"""
        bullish = sum(1 for o in opinions if o.direction == 'bullish' and o.status == 'success')
        bearish = sum(1 for o in opinions if o.direction == 'bearish' and o.status == 'success')
        total = bullish + bearish

        if total == 0:
            return 'neutral'
        if bullish > bearish:
            return 'bullish'
        elif bearish > bullish:
            return 'bearish'
        return 'neutral'

    def _determine_action(self, direction: str, profile: DecisionProfileSchema) -> str:
        """基于方向和持仓状态确定动作"""
        if profile.position_status == PositionType.EMPTY:
            if direction == 'bullish':
                return 'watch'
            elif direction == 'bearish':
                return 'avoid'
            return 'watch'
        else:
            if direction == 'bullish':
                return 'hold'
            elif direction == 'bearish':
                return 'reduce'
            return 'hold'

    @staticmethod
    def _indicator_value(indicators: dict, indicator_id: str) -> Optional[float]:
        """取指标数值；缺失或计算失败一律返回 None（不给默认值）。"""
        result = indicators.get(indicator_id)
        if result is None or result.value is None:
            return None
        if result.status in (
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
        ):
            return None
        return float(result.value)

    @staticmethod
    def _current_price(evidence_pack: EvidencePack) -> Optional[float]:
        item = evidence_pack.get_item('quote_price')
        if item is None or item.value is None:
            return None
        if item.status in (
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
        ):
            return None
        return float(item.value)

    def _get_triggering_conditions(
        self, action: str, indicators: dict, evidence_pack: EvidencePack
    ) -> list[str]:
        """下一步要等的水位——必须是能对着盘面核对的具体数字。

        条件只由已算出的指标推导；指标缺失就少一条，不用"回调至支撑位"
        这类无法检验的话术凑数。
        """
        if action in BEARISH_ACTIONS:
            return self._reattention_conditions(indicators, evidence_pack)
        if action not in BULLISH_ACTIONS:
            return []

        conditions: list[str] = []
        price = self._current_price(evidence_pack)
        sma_20 = self._indicator_value(indicators, 'sma_20')
        boll_lower = self._indicator_value(indicators, 'bollinger_lower')
        rsi = self._indicator_value(indicators, 'rsi_14')

        if price is not None and sma_20 is not None and price > sma_20:
            pullback = (price - sma_20) / price * 100
            conditions.append(
                f"价格回落至 20 日均线 {sma_20:.2f}（现价 {price:.2f}，需回调 {pullback:.1f}%）"
            )
        if boll_lower is not None:
            conditions.append(f"下探布林下轨 {boll_lower:.2f}")
        if rsi is not None and rsi > 50:
            conditions.append(f"RSI(14) 回落至 50 以下（当前 {rsi:.1f}）")

        return conditions

    def _get_invalidating_conditions(
        self, action: str, indicators: dict, evidence_pack: EvidencePack
    ) -> list[str]:
        """判断"这次看法已经错了"的水位，同样要求可核对。

        看多与看空都要有：只给看多结论留证伪条件，等于默认看空不会错。
        """
        if action in BEARISH_ACTIONS:
            return self._bearish_invalidating_conditions(indicators)
        if action not in BULLISH_ACTIONS:
            return []

        conditions: list[str] = []
        sma_50 = self._indicator_value(indicators, 'sma_50')
        sma_20 = self._indicator_value(indicators, 'sma_20')
        atr = self._indicator_value(indicators, 'atr_14')
        revenue_growth = self._indicator_value(indicators, 'revenue_growth_rate')

        support = sma_50 if sma_50 is not None else sma_20
        if support is not None:
            label = "50 日均线" if sma_50 is not None else "20 日均线"
            conditions.append(f"收盘跌破 {label} {support:.2f}")
        if atr is not None:
            conditions.append(f"单日跌幅超过 2×ATR(14)，即 {2 * atr:.2f}")
        if revenue_growth is not None and revenue_growth > 0:
            conditions.append(
                f"下一报告期营收同比转负（当前 {self._as_percent(revenue_growth)}）"
            )

        return conditions

    def _reattention_conditions(
        self, indicators: dict, evidence_pack: EvidencePack
    ) -> list[str]:
        """回避/减仓之后，什么情况下值得把这只票重新捡起来看。

        方向朝上：趋势修复或估值回到自身历史低位。阈值与估值维度判"便宜"
        用同一条线，否则会出现"分位数说便宜、结论仍让你别看"的自相矛盾。
        """
        conditions: list[str] = []
        price = self._current_price(evidence_pack)
        sma_50 = self._indicator_value(indicators, 'sma_50')
        sma_20 = self._indicator_value(indicators, 'sma_20')
        rsi = self._indicator_value(indicators, 'rsi_14')
        pe_percentile = self._indicator_value(indicators, 'pe_percentile')

        trend = sma_50 if sma_50 is not None else sma_20
        if trend is not None:
            label = "50 日均线" if sma_50 is not None else "20 日均线"
            if price is not None and price < trend:
                upside = (trend - price) / price * 100
                conditions.append(
                    f"收盘重新站上 {label} {trend:.2f}（现价 {price:.2f}，需上涨 {upside:.1f}%）"
                )
            else:
                conditions.append(f"收盘持续站稳 {label} {trend:.2f} 之上")
        if pe_percentile is not None and pe_percentile > CHEAP_PERCENTILE:
            conditions.append(
                f"PE 分位回落至 {CHEAP_PERCENTILE:.0f}% 以下（当前 {pe_percentile:.1f}%）"
            )
        if rsi is not None and rsi > 30:
            conditions.append(f"RSI(14) 进入超卖区 30 以下（当前 {rsi:.1f}）")

        return conditions

    def _bearish_invalidating_conditions(self, indicators: dict) -> list[str]:
        """看空判断被证伪的水位。"""
        conditions: list[str] = []
        sma_20 = self._indicator_value(indicators, 'sma_20')
        atr = self._indicator_value(indicators, 'atr_14')
        revenue_growth = self._indicator_value(indicators, 'revenue_growth_rate')

        if sma_20 is not None:
            conditions.append(f"连续 3 个交易日收盘站上 20 日均线 {sma_20:.2f}")
        if atr is not None:
            conditions.append(f"单日涨幅超过 2×ATR(14)，即 {2 * atr:.2f}")
        if revenue_growth is not None and revenue_growth < 0:
            conditions.append(
                f"下一报告期营收同比转正（当前 {self._as_percent(revenue_growth)}）"
            )

        return conditions

    @staticmethod
    def _as_percent(ratio: float) -> str:
        """增长率指标的量纲是比例（0.0634），展示成百分数前必须乘 100。
        直接按 ':.1f%' 打印会把 6.3% 显示成 0.1%。"""
        return f"{ratio * 100:.1f}%"

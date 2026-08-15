"""
Phase 2 Tests

测试指标计算、维度意见、冲突检测和 Runner。
"""

import pytest
from datetime import datetime, timezone

from ..evidence.schemas import (
    EvidencePack, EvidenceBlock, EvidenceItem, EvidenceStatus,
    Instrument, Market, Horizon
)
from ..schemas import DecisionProfileSchema, PositionType
from ..indicators.registry import calculate_all_indicators
from ..dimensions.registry import analyze_all_dimensions
from ..conflict import ConflictDetector
from ..quality_gate import QualityGate, RiskConstraint
from ..runner import DiagnosisRunner


def create_test_evidence_pack() -> EvidencePack:
    """创建测试用 EvidencePack"""
    instrument = Instrument(
        market=Market.CN,
        canonical_symbol="600519.SH",
        exchange="SSE",
        display_name="贵州茅台",
        currency="CNY",
        timezone="Asia/Shanghai",
    )
    pack = EvidencePack(instrument=instrument)

    # 添加财务数据
    block = EvidenceBlock(block_id="fundamentals")
    block.add_item(EvidenceItem(
        evidence_id="fundamentals_revenue",
        status=EvidenceStatus.available,
        value=1000000000,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    block.add_item(EvidenceItem(
        evidence_id="fundamentals_net_income",
        status=EvidenceStatus.available,
        value=500000000,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    block.add_item(EvidenceItem(
        evidence_id="fundamentals_shareholders_equity",
        status=EvidenceStatus.available,
        value=5000000000,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    block.add_item(EvidenceItem(
        evidence_id="fundamentals_total_debt",
        status=EvidenceStatus.available,
        value=2000000000,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    block.add_item(EvidenceItem(
        evidence_id="fundamentals_total_assets",
        status=EvidenceStatus.available,
        value=8000000000,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    pack.add_block(block)

    # 添加估值数据
    val_block = EvidenceBlock(block_id="valuation")
    val_block.add_item(EvidenceItem(
        evidence_id="valuation_pe",
        status=EvidenceStatus.available,
        value=25.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    val_block.add_item(EvidenceItem(
        evidence_id="valuation_pb",
        status=EvidenceStatus.available,
        value=8.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    pack.add_block(val_block)

    # 添加技术数据
    tech_block = EvidenceBlock(block_id="technical")
    tech_block.add_item(EvidenceItem(
        evidence_id="quote_price",
        status=EvidenceStatus.available,
        value=1800.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    tech_block.add_item(EvidenceItem(
        evidence_id="technical_sma_20",
        status=EvidenceStatus.available,
        value=1780.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    tech_block.add_item(EvidenceItem(
        evidence_id="technical_sma_50",
        status=EvidenceStatus.available,
        value=1750.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    tech_block.add_item(EvidenceItem(
        evidence_id="technical_sma_200",
        status=EvidenceStatus.available,
        value=1700.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    tech_block.add_item(EvidenceItem(
        evidence_id="technical_rsi_14",
        status=EvidenceStatus.available,
        value=55.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    tech_block.add_item(EvidenceItem(
        evidence_id="technical_macd",
        status=EvidenceStatus.available,
        value=5.0,
        source="akshare",
        as_of=datetime.now(timezone.utc),
    ))
    pack.add_block(tech_block)

    return pack


class TestIndicators:
    """测试指标计算"""

    def test_calculate_all_indicators(self):
        """测试计算所有指标"""
        pack = create_test_evidence_pack()
        indicators = calculate_all_indicators(pack)

        assert 'roe' in indicators
        assert 'debt_ratio' in indicators
        assert 'pe_ratio' in indicators

        # ROE = 500M / 5000M = 0.1
        assert indicators['roe'].value == pytest.approx(0.1, rel=0.01)

    def test_financial_indicators(self):
        """测试财务指标"""
        pack = create_test_evidence_pack()
        indicators = calculate_all_indicators(pack)

        assert indicators['roe'].value == pytest.approx(0.1, rel=0.01)
        assert indicators['debt_ratio'].value == pytest.approx(0.25, rel=0.01)


class TestDimensions:
    """测试维度意见"""

    def test_analyze_all_dimensions(self):
        """测试分析所有维度"""
        pack = create_test_evidence_pack()
        indicators = calculate_all_indicators(pack)
        opinions = analyze_all_dimensions(pack, indicators, Horizon.medium)

        assert len(opinions) == 6
        assert all(o.status in ('success', 'degraded', 'unavailable', 'failed') for o in opinions)

    def test_financial_quality_dimension(self):
        """测试财务质量维度"""
        pack = create_test_evidence_pack()
        indicators = calculate_all_indicators(pack)
        opinions = analyze_all_dimensions(pack, indicators, Horizon.medium)

        fin_opinion = next(o for o in opinions if o.dimension_id == 'financial_quality')
        assert fin_opinion.status == 'success'
        assert fin_opinion.direction in ('bullish', 'neutral', 'bearish')


class TestValuationDimension:
    """估值维度：分位数量纲是 0–100，判错方向会让低估股票被判成回避。"""

    @staticmethod
    def _analyze(**indicator_values):
        from ..dimensions.valuation import ValuationAnalyzer
        from ..indicators.base import IndicatorResult

        pack = create_test_evidence_pack()
        for evidence_id, value in (
            ('valuation_pe', 20.0), ('valuation_pb', 6.0), ('valuation_ps', 9.0),
        ):
            pack.add_item_to_block('valuation', EvidenceItem(
                evidence_id=evidence_id,
                status=EvidenceStatus.available,
                value=value,
                source="akshare",
                as_of=datetime.now(timezone.utc),
            ))
        indicators = {
            key: IndicatorResult(
                indicator_id=key, value=value, status=EvidenceStatus.available
            )
            for key, value in indicator_values.items()
        }
        return ValuationAnalyzer().analyze(pack, indicators, Horizon.medium)

    def test_low_percentile_is_bullish(self):
        """PE 分位 19.75 是历史低位。按 0–1 量纲读会误判成 >0.8 的高位。"""
        opinion = self._analyze(
            pe_ratio=20.48, pe_percentile=19.75, pb_ratio=6.25, pb_percentile=5.25
        )
        assert opinion.direction == 'bullish'
        assert '19.8% 分位' in opinion.thesis

    def test_high_percentile_is_bearish(self):
        opinion = self._analyze(
            pe_ratio=80.0, pe_percentile=95.0, pb_ratio=12.0, pb_percentile=92.0
        )
        assert opinion.direction == 'bearish'

    def test_high_absolute_pb_alone_is_not_bearish(self):
        """PB 6.25 对白酒是常态，对银行是天价；没有分位数就不给方向。"""
        opinion = self._analyze(pe_ratio=20.0, pb_ratio=6.25)
        assert opinion.direction == 'neutral'
        assert '未据此判断' in opinion.thesis

    def test_conflicting_signals_stay_neutral(self):
        opinion = self._analyze(
            pe_ratio=20.0, pe_percentile=10.0, pb_ratio=6.0, pb_percentile=90.0
        )
        assert opinion.direction == 'neutral'


class TestConclusionConditions:
    """看空结论若不给"何时重新关注"，用户拿到的只是一句"别买"，无法决策。"""

    @staticmethod
    def _indicators(**values):
        from ..indicators.base import IndicatorResult

        return {
            key: IndicatorResult(
                indicator_id=key, value=value, status=EvidenceStatus.available
            )
            for key, value in values.items()
        }

    def test_avoid_gives_reattention_levels(self):
        runner = DiagnosisRunner()
        pack = create_test_evidence_pack()  # quote_price = 1800
        indicators = self._indicators(sma_50=1900.0, rsi_14=55.0, pe_percentile=85.0)

        conditions = runner._get_triggering_conditions('avoid', indicators, pack)

        assert any('50 日均线 1900.00' in c and '需上涨 5.6%' in c for c in conditions)
        assert any('PE 分位回落至 20% 以下' in c for c in conditions)

    def test_avoid_gives_invalidating_levels(self):
        runner = DiagnosisRunner()
        indicators = self._indicators(sma_20=1850.0, atr_14=30.0)

        conditions = runner._get_invalidating_conditions(
            'avoid', indicators, create_test_evidence_pack()
        )

        assert any('20 日均线 1850.00' in c for c in conditions)
        assert any('60.00' in c for c in conditions)  # 2×ATR

    def test_growth_rate_is_rendered_as_percent(self):
        """营收增速指标是比例 0.0634；直接当百分数打印会显示成 0.1%。"""
        runner = DiagnosisRunner()
        indicators = self._indicators(revenue_growth_rate=0.0634)

        conditions = runner._get_invalidating_conditions(
            'hold', indicators, create_test_evidence_pack()
        )

        assert any('6.3%' in c for c in conditions)


class TestConflict:
    """测试冲突检测"""

    def test_no_conflict(self):
        """测试无冲突"""
        detector = ConflictDetector()
        from ..dimensions.base import DimensionOpinion

        opinions = [
            DimensionOpinion(
                dimension_id='valuation',
                horizon=Horizon.medium,
                status='success',
                direction='bullish',
                confidence=0.8,
            ),
            DimensionOpinion(
                dimension_id='financial_quality',
                horizon=Horizon.medium,
                status='success',
                direction='bullish',
                confidence=0.7,
            ),
        ]

        review = detector.detect(opinions, 'medium')
        assert review is None


class TestQualityGate:
    """测试质量门禁"""

    def test_legacy_gate_delegates_to_required_block_gate(self):
        """Runner-facing gate must not bypass market/horizon requirements."""
        gate = QualityGate()
        pack = create_test_evidence_pack()  # Missing identity, quote, and events.
        result = gate.check(pack, 'CN', 'medium')

        assert result.passed is False
        assert result.availability != "actionable"
        assert any("Missing required block" in error for error in result.errors)

    def test_risk_constraint(self):
        """测试风险约束"""
        constraint = RiskConstraint()
        profile = DecisionProfileSchema(position_status=PositionType.EMPTY)
        valid, msg = constraint.validate_action('buy', profile)
        assert valid is True

        valid, msg = constraint.validate_action('sell', profile)
        assert valid is False

    def test_risk_constraint_does_not_invent_position_increment(self):
        constraint = RiskConstraint()
        profile = DecisionProfileSchema(
            position_status=PositionType.HOLDING,
            portfolio_weight=0.25,
        )

        assert constraint.apply_constraints("add", profile, {}) == "add"


class TestRunner:
    """测试 Runner"""

    def test_run_diagnosis(self):
        """测试运行诊断"""
        runner = DiagnosisRunner()
        pack = create_test_evidence_pack()
        profile = DecisionProfileSchema(
            position_status=PositionType.EMPTY,
            primary_horizon='medium',
        )

        advice = runner.run(pack, profile)

        assert advice.conclusion is not None
        assert advice.conclusion.action in ('buy', 'watch', 'avoid', 'hold', 'reduce', 'sell', 'add')
        assert advice.overall_confidence > 0
        assert advice.provenance is not None

    def test_required_evidence_failure_stops_runner_before_analysis(self):
        runner = DiagnosisRunner()
        pack = create_test_evidence_pack()  # Globally high quality, gate-locally incomplete.
        profile = DecisionProfileSchema(
            position_status=PositionType.EMPTY,
            primary_horizon='medium',
        )

        advice = runner.run(pack, profile)

        assert advice.conclusion.action == "watch"
        assert any(
            "Missing required block" in reason
            for reason in advice.conclusion.risk_reasons
        )

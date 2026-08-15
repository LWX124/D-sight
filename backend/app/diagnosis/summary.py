"""
Deterministic Summary Output

确定性摘要输出，用于验证数据链完整性。
先用确定性摘要输出 limited/insufficient，验证数据链后再接 LLM。
"""


from .evidence.schemas import EvidencePack, EvidenceStatus
from .evidence.quality import validate_evidence_quality
from .schemas import DecisionProfileSchema, PositionType


class DeterministicSummary:
    """
    确定性摘要生成器

    基于 EvidencePack 生成确定性诊断摘要。
    不使用 LLM，只基于规则和数据质量。
    """

    def __init__(self, evidence_pack: EvidencePack, decision_profile: DecisionProfileSchema):
        self.evidence_pack = evidence_pack
        self.decision_profile = decision_profile

    def generate(self) -> dict:
        """
        生成确定性摘要

        Returns:
            诊断摘要字典
        """
        # 检查 instrument 是否存在
        if self.evidence_pack.instrument is None:
            # 没有 instrument，直接返回 insufficient
            from .evidence.quality import QualityGateResult
            quality_result = QualityGateResult(
                passed=False,
                availability='insufficient',
                quality_score=0.0,
                completeness=0.0,
                errors=['No instrument specified'],
                warnings=[],
            )
            return self._generate_insufficient_summary(quality_result)

        # 1. 验证数据质量
        quality_result = validate_evidence_quality(
            self.evidence_pack,
            self.evidence_pack.instrument.market.value,
            self.decision_profile.primary_horizon,
        )

        # 2. 如果数据不足，返回 limited/insufficient
        if quality_result.availability == 'insufficient':
            return self._generate_insufficient_summary(quality_result)

        if quality_result.availability == 'limited':
            return self._generate_limited_summary(quality_result)

        # 3. 生成 actionable 摘要
        return self._generate_actionable_summary(quality_result)

    def _generate_insufficient_summary(self, quality_result) -> dict:
        """生成 insufficient 摘要"""
        return {
            'availability': 'insufficient',
            'action': None,
            'confidence': None,
            'reasoning': '数据质量不足，无法产生诊断建议',
            'quality_score': quality_result.quality_score,
            'completeness': quality_result.completeness,
            'errors': quality_result.errors,
            'warnings': quality_result.warnings,
            'missing_blocks': self._get_missing_blocks(),
            'recommendation': '请补充缺失数据后重新诊断',
        }

    def _generate_limited_summary(self, quality_result) -> dict:
        """生成 limited 摘要"""
        # 保守动作：watch/hold/reduce/avoid
        action = self._determine_conservative_action()

        return {
            'availability': 'limited',
            'action': action,
            'confidence': 0.3,  # 低置信度
            'reasoning': '数据质量有限，只能提供保守建议',
            'quality_score': quality_result.quality_score,
            'completeness': quality_result.completeness,
            'errors': quality_result.errors,
            'warnings': quality_result.warnings,
            'missing_blocks': self._get_missing_blocks(),
            'recommendation': '建议补充数据后重新诊断以获得更准确的建议',
        }

    def _generate_actionable_summary(self, quality_result) -> dict:
        """生成 actionable 摘要"""
        # 基于证据的方向判断
        direction = self._determine_direction()
        action = self._determine_action(direction)
        confidence = self._calculate_confidence(quality_result)

        return {
            'availability': 'actionable',
            'action': action,
            'direction': direction,
            'confidence': confidence,
            'reasoning': self._generate_reasoning(direction, action),
            'quality_score': quality_result.quality_score,
            'completeness': quality_result.completeness,
            'errors': quality_result.errors,
            'warnings': quality_result.warnings,
            'missing_blocks': self._get_missing_blocks(),
            'recommendation': self._generate_recommendation(action, direction),
        }

    def _determine_direction(self) -> str:
        """基于证据确定方向"""
        # 简单规则：基于估值和技术指标
        # TODO: 实现更复杂的规则

        # 检查估值
        valuation_item = self.evidence_pack.get_item('valuation_pe')
        if valuation_item and valuation_item.status == EvidenceStatus.available:
            pe = valuation_item.value
            if isinstance(pe, (int, float)):
                if pe < 15:
                    return 'bullish'
                elif pe > 30:
                    return 'bearish'

        return 'neutral'

    def _determine_action(self, direction: str) -> str:
        """基于方向和持仓状态确定动作"""
        position = self.decision_profile.position_status

        if position is PositionType.EMPTY:
            # 空仓：buy/watch/avoid
            if direction == 'bullish':
                return 'watch'  # 保守起见，先观察
            elif direction == 'bearish':
                return 'avoid'
            else:
                return 'watch'
        else:
            # 持仓：add/hold/reduce/sell
            if direction == 'bullish':
                return 'hold'
            elif direction == 'bearish':
                return 'reduce'
            else:
                return 'hold'

    def _determine_conservative_action(self) -> str:
        """确定保守动作"""
        position = self.decision_profile.position_status

        if position is PositionType.EMPTY:
            return 'watch'
        else:
            return 'hold'

    def _calculate_confidence(self, quality_result) -> float:
        """计算置信度"""
        # 基于数据质量计算
        base_confidence = quality_result.quality_score * 0.6 + quality_result.completeness * 0.4
        return min(max(base_confidence, 0.1), 0.9)  # 限制在 0.1-0.9

    def _generate_reasoning(self, direction: str, action: str) -> str:
        """生成推理说明"""
        direction_map = {
            'bullish': '看多',
            'neutral': '中性',
            'bearish': '看空',
        }
        action_map = {
            'buy': '买入',
            'watch': '观望',
            'avoid': '回避',
            'add': '加仓',
            'hold': '持有',
            'reduce': '减仓',
            'sell': '卖出',
        }

        return f"基于当前证据，方向判断为{direction_map.get(direction, direction)}，建议{action_map.get(action, action)}"

    def _generate_recommendation(self, action: str, direction: str) -> str:
        """生成建议说明"""
        if action in ['buy', 'add']:
            return '建议在满足触发条件后执行'
        elif action in ['sell', 'reduce', 'avoid']:
            return '建议关注失效条件，及时止损'
        else:
            return '建议持续关注，等待更明确的信号'

    def _get_missing_blocks(self) -> list[str]:
        """获取缺失的证据块"""
        missing = []
        for block_id, block in self.evidence_pack.blocks.items():
            if block.status in [EvidenceStatus.missing, EvidenceStatus.fetch_failed]:
                missing.append(block_id)
        return missing


def create_deterministic_summary(
    evidence_pack: EvidencePack,
    decision_profile: DecisionProfileSchema,
) -> dict:
    """
    创建确定性摘要

    Args:
        evidence_pack: 证据包
        decision_profile: 决策画像

    Returns:
        诊断摘要字典
    """
    generator = DeterministicSummary(evidence_pack, decision_profile)
    return generator.generate()

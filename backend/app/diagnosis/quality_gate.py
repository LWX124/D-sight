"""
Quality Gate & Risk Constraint

质量门禁和风险约束。
"""

from .evidence.quality import QualityGateResult, validate_evidence_quality
from .evidence.schemas import EvidencePack
from .schemas import DecisionProfileSchema, PositionType


class QualityGate:
    """Compatibility adapter for the canonical market/horizon evidence gate."""

    def check(
        self,
        evidence_pack: EvidencePack,
        market: str,
        horizon: str,
    ) -> QualityGateResult:
        """Validate through the single authoritative evidence gate."""
        return validate_evidence_quality(evidence_pack, market, horizon)


class RiskConstraint:
    """风险约束"""

    # 七态动作校验
    VALID_ACTIONS = {
        PositionType.EMPTY: ["buy", "watch", "avoid"],
        PositionType.HOLDING: ["add", "hold", "reduce", "sell"],
    }

    def validate_action(
        self,
        action: str,
        profile: DecisionProfileSchema,
    ) -> tuple[bool, str]:
        """验证动作是否符合风险约束"""
        valid = self.VALID_ACTIONS.get(profile.position_status, [])
        if action not in valid:
            return False, f"Action '{action}' not valid for position '{profile.position_status.value}'. Valid: {valid}"
        return True, ""

    def apply_constraints(
        self,
        proposed_action: str,
        profile: DecisionProfileSchema,
        indicators: dict,
    ) -> str:
        """应用风险约束，可能降级动作"""
        action = proposed_action

        # Conservative adjustment
        if profile.risk_tolerance == 'conservative':
            if action in ('buy', 'add'):
                # 要求更高安全边际
                val_ind = indicators.get('pe_percentile')
                if val_ind and val_ind.value is not None and val_ind.value > 0.5:
                    action = 'watch' if profile.position_status == PositionType.EMPTY else 'hold'

        return action

"""
Data Quality Gates for Stock Diagnosis

Prevents low-quality inputs from generating positive diagnosis actions.
Defines quality requirements per market and horizon.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional

from .schemas import (
    EVIDENCE_BLOCKS,
    EVIDENCE_BLOCK_WEIGHTS,
    EVIDENCE_STATUS_WEIGHTS,
    EvidencePack,
    EvidenceStatus,
    REQUIRED_BLOCKS,
)


# 每个块里「没有它这块就没意义」的字段。只有这些字段缺失/被阻断才算硬错误；
# 其余期望字段缺失只降分（见 EVIDENCE_STATUS_WEIGHTS）并记 warning。
#
# 为什么要区分：expected_evidence_ids 是「这个块可能有什么」的目录，本就用来算
# 分数。若同一份目录再拿来逐项判死，分数阈值就永远不会成为约束——任何一个字段
# 缺失都直接 fail，minimum_quality_score 变成死代码。判「缺多少」只能有一处，
# 就是阈值；硬门槛只留给缺了就无法得出结论的那几项。
CRITICAL_EVIDENCE_IDS: dict[str, list[str]] = {
    'identity': ['identity_name'],
    'quote': ['quote_price'],          # 没有价格，任何结论都无从谈起
    'daily_bars': ['daily_bars_close'],
    'fundamentals': ['fundamentals_revenue', 'fundamentals_net_income'],
    'valuation': ['valuation_pe'],
    # technical: 单个指标都不是必需的，指标算不出来由分数体现
    # events: 事件的「没有」本身就是信息——从不分红、不送转的公司完全正常，
    #         把它当数据缺口会把这类股票全判死
}

# 只有价格族的证据需要按时效判断。事件（分红/披露日）天然是几个月前的事实，
# 用行情的时钟去量它，等于要求每只股票每周都分红。
PRICE_FRESHNESS_BLOCKS = frozenset({'quote', 'daily_bars', 'technical'})


@dataclass
class QualityGate:
    """Quality gate configuration for a specific market and horizon."""
    market: str
    horizon: str
    required_blocks: list[str]
    minimum_completeness: float  # 0.0 to 1.0
    minimum_quality_score: float  # 0.0 to 1.0
    allowed_statuses: list[EvidenceStatus]
    blocked_statuses: list[EvidenceStatus]
    # 行情时效按「自然日」而非小时衡量：Phase 0 没有实时行情，quote_price 就是
    # 上一交易日的收盘价，周一早上看到的必然是上周五的数据（约 65 小时）。
    # 用小时窗口去卡日线，等于周一永远不可用。
    max_price_age_days: Optional[int] = None


# Quality gate configurations
QUALITY_GATES = {
    ('CN', 'short'): QualityGate(
        market='CN',
        horizon='short',
        required_blocks=REQUIRED_BLOCKS['CN']['short'],
        minimum_completeness=0.7,
        minimum_quality_score=0.6,
        allowed_statuses=[EvidenceStatus.available, EvidenceStatus.partial, EvidenceStatus.fallback],
        blocked_statuses=[
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
            EvidenceStatus.stale,
        ],
        max_price_age_days=5,    # 覆盖周末 + 1 天假；短线本就不该在长假里给可执行建议
    ),
    ('CN', 'medium'): QualityGate(
        market='CN',
        horizon='medium',
        required_blocks=REQUIRED_BLOCKS['CN']['medium'],
        minimum_completeness=0.6,
        minimum_quality_score=0.5,
        allowed_statuses=[EvidenceStatus.available, EvidenceStatus.partial, EvidenceStatus.fallback],
        blocked_statuses=[
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
            EvidenceStatus.stale,
        ],
        max_price_age_days=7,
    ),
    ('CN', 'long'): QualityGate(
        market='CN',
        horizon='long',
        required_blocks=REQUIRED_BLOCKS['CN']['long'],
        minimum_completeness=0.5,
        minimum_quality_score=0.4,
        allowed_statuses=[EvidenceStatus.available, EvidenceStatus.partial, EvidenceStatus.fallback],
        blocked_statuses=[
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
            EvidenceStatus.stale,
        ],
        max_price_age_days=30,
    ),
    ('US', 'short'): QualityGate(
        market='US',
        horizon='short',
        required_blocks=REQUIRED_BLOCKS['US']['short'],
        minimum_completeness=0.7,
        minimum_quality_score=0.6,
        allowed_statuses=[EvidenceStatus.available, EvidenceStatus.partial, EvidenceStatus.fallback],
        blocked_statuses=[
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
            EvidenceStatus.stale,
        ],
        max_price_age_days=5,    # 覆盖周末 + 1 天假；短线本就不该在长假里给可执行建议
    ),
    ('US', 'medium'): QualityGate(
        market='US',
        horizon='medium',
        required_blocks=REQUIRED_BLOCKS['US']['medium'],
        minimum_completeness=0.6,
        minimum_quality_score=0.5,
        allowed_statuses=[EvidenceStatus.available, EvidenceStatus.partial, EvidenceStatus.fallback],
        blocked_statuses=[
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
            EvidenceStatus.stale,
        ],
        max_price_age_days=7,
    ),
    ('US', 'long'): QualityGate(
        market='US',
        horizon='long',
        required_blocks=REQUIRED_BLOCKS['US']['long'],
        minimum_completeness=0.5,
        minimum_quality_score=0.4,
        allowed_statuses=[EvidenceStatus.available, EvidenceStatus.partial, EvidenceStatus.fallback],
        blocked_statuses=[
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
            EvidenceStatus.stale,
        ],
        max_price_age_days=30,
    ),
}


@dataclass
class QualityGateResult:
    """Result of quality gate validation."""
    passed: bool
    availability: str  # 'actionable', 'limited', 'insufficient'
    errors: list[str]
    warnings: list[str]
    quality_score: float
    completeness: float


class DataQualityGates:
    """Data quality gate validator."""

    def validate(
        self,
        evidence_pack: EvidencePack,
        market: str,
        horizon: str,
    ) -> QualityGateResult:
        """
        Validate an evidence pack against quality gates.

        Args:
            evidence_pack: The evidence pack to validate
            market: Market code ('CN', 'US', etc.)
            horizon: Investment horizon ('short', 'medium', 'long')

        Returns:
            QualityGateResult with validation results
        """
        gate_key = (market, horizon)
        gate = QUALITY_GATES.get(gate_key)

        if not gate:
            return QualityGateResult(
                passed=False,
                availability='insufficient',
                errors=[f"No quality gate defined for {market}/{horizon}"],
                warnings=[],
                quality_score=0.0,
                completeness=0.0,
            )

        errors: list[str] = []
        warnings: list[str] = []
        weighted_quality = 0.0
        weighted_completeness = 0.0
        total_weight = 0.0
        now = datetime.now(timezone.utc)

        if evidence_pack.instrument is None:
            errors.append("Missing instrument")
        elif evidence_pack.instrument.market.value != market:
            errors.append(
                "Instrument market mismatch: "
                f"{evidence_pack.instrument.market.value} != {market}"
            )

        # Check required blocks
        for block_id in gate.required_blocks:
            if block_id not in evidence_pack.blocks:
                errors.append(f"Missing required block: {block_id}")
                block = None
            else:
                block = evidence_pack.blocks[block_id]
                if block.status in gate.blocked_statuses:
                    errors.append(
                        f"Required block {block_id} has blocking status: {block.status.value}"
                    )

            block_weight = EVIDENCE_BLOCK_WEIGHTS.get(block_id, 0.5)
            total_weight += block_weight
            expected_ids = EVIDENCE_BLOCKS.get(block_id, {}).get(
                "expected_evidence_ids", []
            )
            if block is None:
                continue

            if expected_ids:
                weighted_quality += block_weight * sum(
                    EVIDENCE_STATUS_WEIGHTS.get(block.items[evidence_id].status, 0.0)
                    if evidence_id in block.items else 0.0
                    for evidence_id in expected_ids
                ) / len(expected_ids)
                weighted_completeness += block_weight * sum(
                    evidence_id in block.items
                    and block.items[evidence_id].status == EvidenceStatus.available
                    for evidence_id in expected_ids
                ) / len(expected_ids)
            else:
                weighted_quality += block_weight * evidence_pack._compute_block_field_score(block)
                weighted_completeness += (
                    block_weight * evidence_pack._compute_block_completeness(block)
                )

            critical_ids = CRITICAL_EVIDENCE_IDS.get(block_id, [])
            for evidence_id in expected_ids:
                item = block.items.get(evidence_id)
                critical = evidence_id in critical_ids

                if item is None:
                    message = f"Missing expected evidence {evidence_id} in required block {block_id}"
                    (errors if critical else warnings).append(message)
                    continue
                if item.status in gate.blocked_statuses:
                    message = (
                        f"Evidence {evidence_id} has blocked status: {item.status.value}"
                        + (f" ({item.missing_reason})" if item.missing_reason else "")
                    )
                    (errors if critical else warnings).append(message)

                if not (critical and block_id in PRICE_FRESHNESS_BLOCKS and gate.max_price_age_days):
                    continue
                evidence_time = self._as_utc(item.as_of or item.fetched_at)
                if evidence_time is None:
                    errors.append(
                        f"Required evidence {evidence_id} has no freshness timestamp"
                    )
                    continue
                # 行情的 as_of 是「哪个交易日」，按自然日相减；用时长相减会让
                # 同一个交易日的数据在一天之内忽过忽不过。
                age_days = (now.date() - evidence_time.date()).days
                if age_days > gate.max_price_age_days:
                    errors.append(
                        f"Required evidence {evidence_id} is stale for {market}/{horizon}: "
                        f"{age_days} days old, window is {gate.max_price_age_days} days"
                    )

        quality_score = weighted_quality / total_weight if total_weight else 0.0
        completeness = weighted_completeness / total_weight if total_weight else 0.0

        # Check completeness
        if completeness < gate.minimum_completeness:
            errors.append(
                f"Completeness {completeness:.2f} < "
                f"minimum {gate.minimum_completeness:.2f}"
            )

        # Check quality score
        if quality_score < gate.minimum_quality_score:
            errors.append(
                f"Quality score {quality_score:.2f} < "
                f"minimum {gate.minimum_quality_score:.2f}"
            )

        # Determine availability
        if errors:
            # Check if we can still provide limited analysis
            if quality_score > 0.3:
                availability = 'limited'
            else:
                availability = 'insufficient'
        else:
            availability = 'actionable'

        return QualityGateResult(
            passed=len(errors) == 0,
            availability=availability,
            errors=errors,
            warnings=warnings,
            quality_score=quality_score,
            completeness=completeness,
        )

    @staticmethod
    def _as_utc(value: datetime | date | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, time.min, tzinfo=timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# Global gates instance
_gates: Optional[DataQualityGates] = None


def get_quality_gates() -> DataQualityGates:
    """Get the global quality gates instance."""
    global _gates
    if _gates is None:
        _gates = DataQualityGates()
    return _gates


def validate_evidence_quality(
    evidence_pack: EvidencePack,
    market: str,
    horizon: str,
) -> QualityGateResult:
    """
    Validate evidence pack quality.

    Args:
        evidence_pack: The evidence pack to validate
        market: Market code ('CN', 'US', etc.)
        horizon: Investment horizon ('short', 'medium', 'long')

    Returns:
        QualityGateResult with validation results
    """
    return get_quality_gates().validate(evidence_pack, market, horizon)

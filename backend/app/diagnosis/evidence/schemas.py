"""
EvidencePack Schema Definition

Defines the core data contracts for stock diagnosis evidence.
This is the foundation for Phase 0 capability verification.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Optional, Union
import json


class EvidenceStatus(Enum):
    """Status of evidence data quality."""
    available = "available"
    partial = "partial"
    fallback = "fallback"
    stale = "stale"
    estimated = "estimated"
    missing = "missing"
    not_supported = "not_supported"
    fetch_failed = "fetch_failed"


class Market(Enum):
    """Supported markets."""
    CN = "CN"  # A-share (China)
    US = "US"  # US stocks
    HK = "HK"  # Hong Kong (Phase 2)
    JP = "JP"  # Japan (Phase 3)
    KR = "KR"  # Korea (Phase 3)


class Horizon(Enum):
    """Investment time horizons."""
    short = "short"  # Current execution conditions
    medium = "medium"  # 1-4 quarters improvement
    long = "long"  # Business quality vs price


@dataclass
class EvidenceItem:
    """Individual evidence item with full provenance."""
    evidence_id: str
    status: EvidenceStatus
    value: Optional[Union[str, int, float, dict, list]] = None
    source: Optional[str] = None
    source_record_id: Optional[str] = None
    as_of: Optional[Union[datetime, date]] = None
    fetched_at: Optional[datetime] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    period: Optional[str] = None
    fallback_from: Optional[str] = None
    missing_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'evidence_id': self.evidence_id,
            'status': self.status.value,
            'value': self.value,
            'source': self.source,
            'source_record_id': self.source_record_id,
            'as_of': self.as_of.isoformat() if self.as_of else None,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
            'currency': self.currency,
            'unit': self.unit,
            'period': self.period,
            'fallback_from': self.fallback_from,
            'missing_reason': self.missing_reason,
            'warnings': self.warnings,
        }


@dataclass
class EvidenceBlock:
    """Group of related evidence items."""
    block_id: str
    items: dict[str, EvidenceItem] = field(default_factory=dict)
    status: EvidenceStatus = EvidenceStatus.missing  # 空块默认为 missing，不是 available
    completeness: float = 0.0  # 0.0 to 1.0
    _on_change: Optional[Callable[[], None]] = field(
        default=None, init=False, repr=False, compare=False
    )

    def add_item(self, item: EvidenceItem):
        """Add an evidence item to the block."""
        self.items[item.evidence_id] = item
        self._update_status()
        if self._on_change is not None:
            self._on_change()

    def _update_status(self):
        """
        Update block status based on item statuses.

        使用完整的 8 态聚合表：
        1. 空块 → missing
        2. 全部 not_supported → not_supported
        3. 全部 available → available
        4. 混合可用状态 → partial（除非每个相关 item 共享同一降级状态）
        5. 同质降级状态保留原状态
        6. 混合无可选值 → 选择最具信息量的失败状态
        7. fetch_failed 区别于 missing
        """
        if not self.items:
            self.status = EvidenceStatus.missing
            self.completeness = 0.0
            return

        relevant = [item for item in self.items.values() if item.status != EvidenceStatus.not_supported]

        # 全部 not_supported
        if not relevant:
            self.status = EvidenceStatus.not_supported
            self.completeness = 1.0  # not_supported 是预期的，不是缺口
            return

        statuses = [item.status for item in relevant]
        available_count = sum(1 for s in statuses if s == EvidenceStatus.available)
        self.completeness = available_count / len(relevant)

        # 检查是否所有 relevant item 共享同一状态
        unique_statuses = set(statuses)
        if len(unique_statuses) == 1:
            self.status = statuses[0]
            return

        usable_statuses = {
            EvidenceStatus.available,
            EvidenceStatus.partial,
            EvidenceStatus.fallback,
            EvidenceStatus.stale,
            EvidenceStatus.estimated,
        }
        if unique_statuses & usable_statuses:
            self.status = EvidenceStatus.partial
        elif EvidenceStatus.fetch_failed in unique_statuses:
            self.status = EvidenceStatus.fetch_failed
        else:
            self.status = EvidenceStatus.missing


@dataclass
class Instrument:
    """Canonical stock instrument identifier."""
    market: Market
    canonical_symbol: str
    exchange: Optional[str]
    display_name: Optional[str] = None
    currency: str = "USD"
    timezone: str = "UTC"
    original_input: Optional[str] = None
    normalization_method: Optional[str] = None
    ambiguity_resolved: bool = False
    candidates: Optional[list[str]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'market': self.market.value,
            'canonical_symbol': self.canonical_symbol,
            'exchange': self.exchange,
            'display_name': self.display_name,
            'currency': self.currency,
            'timezone': self.timezone,
            'original_input': self.original_input,
            'normalization_method': self.normalization_method,
            'ambiguity_resolved': self.ambiguity_resolved,
            'candidates': self.candidates,
        }


@dataclass
class EvidencePack:
    """
    Complete evidence package for stock diagnosis.

    This is the primary input for all diagnosis dimensions.
    All dimensions share the same EvidencePack to ensure consistency.
    """
    schema_version: str = "1.0"
    instrument: Optional[Instrument] = None
    blocks: dict[str, EvidenceBlock] = field(default_factory=dict)
    quality_score: float = 0.0  # 0.0 to 1.0
    completeness: float = 0.0  # 0.0 to 1.0
    as_of: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    provider_attempts: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_block(self, block: EvidenceBlock):
        """Add an evidence block."""
        self.blocks[block.block_id] = block
        block._on_change = self._update_metrics
        self._update_metrics()

    def get_block(self, block_id: str) -> Optional[EvidenceBlock]:
        """Get an evidence block by ID."""
        return self.blocks.get(block_id)

    def get_item(self, evidence_id: str) -> Optional[EvidenceItem]:
        """Get an evidence item by ID across all blocks."""
        for block in self.blocks.values():
            if evidence_id in block.items:
                return block.items[evidence_id]
        return None

    def add_item_to_block(self, block_id: str, item: EvidenceItem):
        """
        Add an evidence item to a block and recalculate pack-level metrics.

        Prefer this over block.add_item() directly when building an EvidencePack,
        so that quality_score and completeness stay in sync.
        """
        if block_id not in self.blocks:
            raise KeyError(f"Block '{block_id}' not found in EvidencePack")
        self.blocks[block_id].add_item(item)

    def _update_metrics(self):
        """
        Update quality score and completeness metrics.

        使用两级聚合：
        1. 计算每个 block 的 field_score
        2. 每个适用 block 只贡献一次 block_weight

        block_weight * field_score / Σ(applicable block_weight)

        这样：
        - block 内 item 数量变化不会改变该块在 pack 中的总权重
        - 空块和未返回字段不进入分母
        """
        if not self.blocks:
            self.quality_score = 0.0
            self.completeness = 0.0
            return

        total_weight = 0.0
        weighted_quality = 0.0
        total_available_weight = 0.0
        total_max_weight = 0.0

        for block in self.blocks.values():
            if block.status == EvidenceStatus.not_supported:
                continue
            block_weight = EVIDENCE_BLOCK_WEIGHTS.get(block.block_id, 0.5)

            # 计算 block 内 field_score
            field_score = self._compute_block_field_score(block)

            # 每个 block 只贡献一次权重
            weighted_quality += block_weight * field_score
            total_weight += block_weight

            block_completeness = self._compute_block_completeness(block)
            total_available_weight += block_weight * block_completeness
            total_max_weight += block_weight

        self.quality_score = weighted_quality / total_weight if total_weight > 0 else 0.0
        self.completeness = total_available_weight / total_max_weight if total_max_weight > 0 else 0.0

    def _compute_block_field_score(self, block: EvidenceBlock) -> float:
        """
        计算单个 block 的 field_score。

        field_score(block) = Σ(status_coefficient(expected field)) / expected_field_count

        如果 block 没有预期字段定义，使用实际 item 的平均系数。
        如果预期字段与实际 item_id 不完全匹配，使用 block 内实际 item 的状态。
        """
        block_def = EVIDENCE_BLOCKS.get(block.block_id, {})
        expected_fields = block_def.get('expected_evidence_ids', [])

        if expected_fields:
            return sum(
                EVIDENCE_STATUS_WEIGHTS.get(block.items[evidence_id].status, 0.0)
                if evidence_id in block.items else 0.0
                for evidence_id in expected_fields
            ) / len(expected_fields)

        if not block.items:
            return 0.0

        # 排除 not_supported 项
        relevant_items = [
            item for item in block.items.values()
            if item.status != EvidenceStatus.not_supported
        ]

        if not relevant_items:
            return 0.0

        total_score = sum(
            EVIDENCE_STATUS_WEIGHTS.get(item.status, 0.0)
            for item in relevant_items
        )
        return total_score / len(relevant_items)

    @staticmethod
    def _compute_block_completeness(block: EvidenceBlock) -> float:
        expected_fields = EVIDENCE_BLOCKS.get(block.block_id, {}).get(
            'expected_evidence_ids', []
        )
        if expected_fields:
            return sum(
                1
                for evidence_id in expected_fields
                if evidence_id in block.items
                and block.items[evidence_id].status == EvidenceStatus.available
            ) / len(expected_fields)
        relevant = [
            item for item in block.items.values()
            if item.status != EvidenceStatus.not_supported
        ]
        if not relevant:
            return 0.0
        return sum(item.status == EvidenceStatus.available for item in relevant) / len(relevant)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'schema_version': self.schema_version,
            'instrument': self.instrument.to_dict() if self.instrument else None,
            'blocks': {
                block_id: {
                    'block_id': block.block_id,
                    'status': block.status.value,
                    'completeness': block.completeness,
                    'items': {
                        item_id: item.to_dict()
                        for item_id, item in block.items.items()
                    }
                }
                for block_id, block in self.blocks.items()
            },
            'quality_score': self.quality_score,
            'completeness': self.completeness,
            'as_of': self.as_of.isoformat() if self.as_of else None,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
            'provider_attempts': self.provider_attempts,
            'warnings': self.warnings,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)


# Required evidence blocks per market and horizon
REQUIRED_BLOCKS = {
    'CN': {
        'short': ['identity', 'quote', 'daily_bars', 'technical', 'events'],
        'medium': ['identity', 'quote', 'fundamentals', 'valuation', 'events'],
        'long': ['identity', 'quote', 'fundamentals', 'valuation', 'ownership'],
    },
    'US': {
        'short': ['identity', 'quote', 'daily_bars', 'technical', 'events'],
        'medium': ['identity', 'quote', 'fundamentals', 'valuation', 'events'],
        'long': ['identity', 'quote', 'fundamentals', 'valuation', 'ownership'],
    },
}

# Evidence block definitions
EVIDENCE_BLOCKS = {
    'identity': {
        'description': 'Company identity and basic information',
        'expected_evidence_ids': [
            'identity_name', 'identity_sector', 'identity_industry', 'identity_listing_date'
        ],
    },
    'quote': {
        'description': 'Current and recent price quotes',
        'expected_evidence_ids': [
            'quote_price', 'quote_volume', 'quote_market_cap', 'quote_pe_ratio'
        ],
    },
    'daily_bars': {
        'description': 'Historical daily price bars',
        'expected_evidence_ids': [
            'daily_bars_open', 'daily_bars_high', 'daily_bars_low',
            'daily_bars_close', 'daily_bars_volume'
        ],
    },
    'technical': {
        'description': 'Technical indicators and analysis',
        'expected_evidence_ids': [
            # 字段名须与 marketdata 产出、indicators 消费的一致（rsi 带窗口后缀）
            'technical_sma_20', 'technical_sma_50', 'technical_rsi_14', 'technical_macd'
        ],
    },
    'fundamentals': {
        'description': 'Financial statements and ratios',
        'expected_evidence_ids': [
            'fundamentals_revenue', 'fundamentals_net_income', 'fundamentals_eps',
            'fundamentals_roe', 'fundamentals_debt_ratio'
        ],
    },
    'valuation': {
        'description': 'Valuation metrics and analysis',
        'expected_evidence_ids': [
            'valuation_pe', 'valuation_pb', 'valuation_ps', 'valuation_ev_ebitda'
        ],
    },
    'events': {
        'description': 'Corporate events and announcements',
        'expected_evidence_ids': ['events_earnings', 'events_dividends', 'events_splits'],
    },
    'news': {
        'description': 'Recent news and sentiment',
        'expected_evidence_ids': ['news_headlines', 'news_sentiment_score'],
    },
    'market_context': {
        'description': 'Market and sector context',
        'expected_evidence_ids': [
            'market_context_sector_performance', 'market_context_market_phase'
        ],
    },
    'ownership': {
        'description': 'Shareholder structure and insider activity',
        'expected_evidence_ids': ['ownership_major_holders', 'ownership_insider_transactions'],
    },
    'capital_flow': {
        'description': 'Capital flow analysis (market-specific)',
        'expected_evidence_ids': ['capital_flow_net_inflow', 'capital_flow_institutional_flow'],
    },
    'portfolio_context': {
        'description': 'Portfolio context (if applicable)',
        'expected_evidence_ids': ['portfolio_current_position', 'portfolio_weight'],
    },
}

# Block-level importance weights for quality scoring.
# Core data blocks (quote, fundamentals) have higher weight than
# supplementary blocks (news, capital_flow). Aligns with REQUIRED_BLOCKS
# so missing a required block has a larger quality impact.
EVIDENCE_BLOCK_WEIGHTS = {
    'identity': 0.5,
    'quote': 1.0,           # Essential for any diagnosis
    'daily_bars': 0.8,
    'technical': 0.7,
    'fundamentals': 1.0,    # Essential for medium/long-term
    'valuation': 0.9,
    'events': 0.7,
    'news': 0.4,            # Supplementary, high noise
    'market_context': 0.6,
    'ownership': 0.5,
    'capital_flow': 0.4,    # Supplementary, not supported for all markets
    'portfolio_context': 0.5,
}

# Quality coefficient per evidence status.
# not_supported items are excluded from the denominator entirely
# (they represent a market limitation, not a data gap).
EVIDENCE_STATUS_WEIGHTS = {
    EvidenceStatus.available: 1.0,
    EvidenceStatus.partial: 0.5,
    EvidenceStatus.fallback: 0.3,
    EvidenceStatus.stale: 0.1,
    EvidenceStatus.estimated: 0.4,
    EvidenceStatus.missing: 0.0,
    EvidenceStatus.fetch_failed: 0.0,
}


def create_evidence_pack(instrument: Instrument) -> EvidencePack:
    """Create a new EvidencePack for an instrument."""
    pack = EvidencePack(
        instrument=instrument,
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )

    # Initialize empty blocks
    for block_id in EVIDENCE_BLOCKS:
        block = EvidenceBlock(block_id=block_id)
        pack.add_block(block)

    return pack


def validate_evidence_pack(pack: EvidencePack, market: str, horizon: str) -> list[str]:
    """
    Validate an EvidencePack against requirements.

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Check required blocks
    required = REQUIRED_BLOCKS.get(market, {}).get(horizon, [])
    for block_id in required:
        if block_id not in pack.blocks:
            errors.append(f"Missing required block: {block_id}")
        elif pack.blocks[block_id].status == EvidenceStatus.missing:
            errors.append(f"Block {block_id} has no data")

    # Check instrument
    if not pack.instrument:
        errors.append("Missing instrument")
    elif pack.instrument.market.value != market:
        errors.append(f"Instrument market mismatch: {pack.instrument.market.value} != {market}")

    # Check evidence items have required fields
    for block_id, block in pack.blocks.items():
        for item_id, item in block.items.items():
            if item.status == EvidenceStatus.available:
                if not item.source:
                    errors.append(f"Evidence {item_id} missing source")
                if not item.as_of:
                    errors.append(f"Evidence {item_id} missing as_of timestamp")

    return errors

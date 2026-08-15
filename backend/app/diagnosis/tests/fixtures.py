"""
Test Fixtures for Stock Diagnosis Phase 0

Provides representative test data for instrument normalization and evidence validation.
"""

from datetime import datetime, date, timezone
from ..evidence.schemas import (
    EVIDENCE_BLOCKS,
    Instrument, Market, EvidenceItem, EvidenceBlock, EvidencePack, EvidenceStatus
)


def _fill_expected_fields(block: EvidenceBlock, source: str) -> None:
    """Materialize a complete canonical block for gate-positive fixtures."""
    for evidence_id in EVIDENCE_BLOCKS[block.block_id]["expected_evidence_ids"]:
        if evidence_id not in block.items:
            block.add_item(
                EvidenceItem(
                    evidence_id=evidence_id,
                    status=EvidenceStatus.available,
                    value=f"fixture:{evidence_id}",
                    source=source,
                    as_of=datetime.now(timezone.utc),
                    fetched_at=datetime.now(timezone.utc),
                )
            )


# A-Share Test Fixtures
CN_FIXTURES = {
    'normal': Instrument(
        market=Market.CN,
        canonical_symbol='600519.SH',
        exchange='SSE',
        display_name='贵州茅台',
        currency='CNY',
        timezone='Asia/Shanghai',
        original_input='600519',
        normalization_method='code_pattern',
    ),
    'normal_sz': Instrument(
        market=Market.CN,
        canonical_symbol='000001.SZ',
        exchange='SZSE',
        display_name='平安银行',
        currency='CNY',
        timezone='Asia/Shanghai',
        original_input='000001',
        normalization_method='code_pattern',
    ),
    'normal_bj': Instrument(
        market=Market.CN,
        canonical_symbol='430047.BJ',
        exchange='BSE',
        display_name='诺思兰德',
        currency='CNY',
        timezone='Asia/Shanghai',
        original_input='430047',
        normalization_method='code_pattern',
    ),
    'missing': Instrument(
        market=Market.CN,
        canonical_symbol='999999.SH',
        exchange='SSE',
        display_name=None,
        currency='CNY',
        timezone='Asia/Shanghai',
        original_input='999999',
        normalization_method='code_pattern',
    ),
    'suspended': Instrument(
        market=Market.CN,
        canonical_symbol='000002.SZ',
        exchange='SZSE',
        display_name='万科A',
        currency='CNY',
        timezone='Asia/Shanghai',
        original_input='000002',
        normalization_method='code_pattern',
    ),
}

# US Test Fixtures
US_FIXTURES = {
    'normal': Instrument(
        market=Market.US,
        canonical_symbol='AAPL',
        exchange='NASDAQ',
        display_name='Apple Inc.',
        currency='USD',
        timezone='America/New_York',
        original_input='AAPL',
        normalization_method='ticker_pattern',
    ),
    'normal_nyse': Instrument(
        market=Market.US,
        canonical_symbol='MSFT',
        exchange='NYSE',
        display_name='Microsoft Corporation',
        currency='USD',
        timezone='America/New_York',
        original_input='MSFT',
        normalization_method='ticker_pattern',
    ),
    'missing': Instrument(
        market=Market.US,
        canonical_symbol='ZZZZZ',
        exchange='NASDAQ',
        display_name=None,
        currency='USD',
        timezone='America/New_York',
        original_input='ZZZZZ',
        normalization_method='ticker_pattern',
    ),
}

# Evidence Pack Fixtures
def create_cn_evidence_pack(instrument: Instrument = None) -> EvidencePack:
    """Create a sample A-share evidence pack with all required blocks."""
    if instrument is None:
        instrument = CN_FIXTURES['normal']

    pack = EvidencePack(
        instrument=instrument,
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )

    # Add identity block
    identity_block = EvidenceBlock(block_id='identity')
    identity_block.add_item(EvidenceItem(
        evidence_id='identity_name',
        status=EvidenceStatus.available,
        value='贵州茅台',
        source='akshare',
        as_of=date(2024, 1, 1),
        fetched_at=datetime.now(timezone.utc),
    ))
    identity_block.add_item(EvidenceItem(
        evidence_id='identity_sector',
        status=EvidenceStatus.available,
        value='食品饮料',
        source='akshare',
        as_of=date(2024, 1, 1),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(identity_block, "akshare")
    pack.add_block(identity_block)

    # Add quote block
    quote_block = EvidenceBlock(block_id='quote')
    quote_block.add_item(EvidenceItem(
        evidence_id='quote_price',
        status=EvidenceStatus.available,
        value=1800.0,
        source='akshare',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        currency='CNY',
    ))
    quote_block.add_item(EvidenceItem(
        evidence_id='quote_volume',
        status=EvidenceStatus.available,
        value=1000000,
        source='akshare',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(quote_block, "akshare")
    pack.add_block(quote_block)

    # Add fundamentals block
    fundamentals_block = EvidenceBlock(block_id='fundamentals')
    fundamentals_block.add_item(EvidenceItem(
        evidence_id='fundamentals_revenue',
        status=EvidenceStatus.available,
        value=100000000000,  # 1000亿
        source='akshare',
        as_of=date(2023, 12, 31),
        fetched_at=datetime.now(timezone.utc),
        currency='CNY',
        period='2023-12-31',
    ))
    fundamentals_block.add_item(EvidenceItem(
        evidence_id='fundamentals_net_income',
        status=EvidenceStatus.available,
        value=50000000000,  # 500亿
        source='akshare',
        as_of=date(2023, 12, 31),
        fetched_at=datetime.now(timezone.utc),
        currency='CNY',
        period='2023-12-31',
    ))
    _fill_expected_fields(fundamentals_block, "akshare")
    pack.add_block(fundamentals_block)

    # Add valuation block
    valuation_block = EvidenceBlock(block_id='valuation')
    valuation_block.add_item(EvidenceItem(
        evidence_id='valuation_pe',
        status=EvidenceStatus.available,
        value=30.0,
        source='akshare',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(valuation_block, "akshare")
    pack.add_block(valuation_block)

    # Add events block
    events_block = EvidenceBlock(block_id='events')
    events_block.add_item(EvidenceItem(
        evidence_id='events_earnings',
        status=EvidenceStatus.available,
        value={'next_earnings': '2024-03-30'},
        source='akshare',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(events_block, "akshare")
    pack.add_block(events_block)

    # Add technical block
    technical_block = EvidenceBlock(block_id='technical')
    technical_block.add_item(EvidenceItem(
        evidence_id='technical_sma_20',
        status=EvidenceStatus.available,
        value=1750.0,
        source='akshare',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    pack.add_block(technical_block)

    # Add market_context block
    market_context_block = EvidenceBlock(block_id='market_context')
    market_context_block.add_item(EvidenceItem(
        evidence_id='market_phase',
        status=EvidenceStatus.available,
        value='bull',
        source='akshare',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    pack.add_block(market_context_block)

    return pack


def create_us_evidence_pack(instrument: Instrument = None) -> EvidencePack:
    """Create a sample US stock evidence pack with all required blocks."""
    if instrument is None:
        instrument = US_FIXTURES['normal']

    pack = EvidencePack(
        instrument=instrument,
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )

    # Add identity block
    identity_block = EvidenceBlock(block_id='identity')
    identity_block.add_item(EvidenceItem(
        evidence_id='identity_name',
        status=EvidenceStatus.available,
        value='Apple Inc.',
        source='yfinance',
        as_of=date(2024, 1, 1),
        fetched_at=datetime.now(timezone.utc),
    ))
    identity_block.add_item(EvidenceItem(
        evidence_id='identity_sector',
        status=EvidenceStatus.available,
        value='Technology',
        source='yfinance',
        as_of=date(2024, 1, 1),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(identity_block, "yfinance")
    pack.add_block(identity_block)

    # Add quote block
    quote_block = EvidenceBlock(block_id='quote')
    quote_block.add_item(EvidenceItem(
        evidence_id='quote_price',
        status=EvidenceStatus.available,
        value=180.0,
        source='yfinance',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        currency='USD',
    ))
    quote_block.add_item(EvidenceItem(
        evidence_id='quote_volume',
        status=EvidenceStatus.available,
        value=50000000,
        source='yfinance',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(quote_block, "yfinance")
    pack.add_block(quote_block)

    # Add fundamentals block
    fundamentals_block = EvidenceBlock(block_id='fundamentals')
    fundamentals_block.add_item(EvidenceItem(
        evidence_id='fundamentals_revenue',
        status=EvidenceStatus.available,
        value=394328000000,  # $394B
        source='yfinance',
        as_of=date(2023, 9, 30),
        fetched_at=datetime.now(timezone.utc),
        currency='USD',
        period='2023-09-30',
    ))
    fundamentals_block.add_item(EvidenceItem(
        evidence_id='fundamentals_net_income',
        status=EvidenceStatus.available,
        value=96995000000,  # $97B
        source='yfinance',
        as_of=date(2023, 9, 30),
        fetched_at=datetime.now(timezone.utc),
        currency='USD',
        period='2023-09-30',
    ))
    _fill_expected_fields(fundamentals_block, "yfinance")
    pack.add_block(fundamentals_block)

    # Add valuation block
    valuation_block = EvidenceBlock(block_id='valuation')
    valuation_block.add_item(EvidenceItem(
        evidence_id='valuation_pe',
        status=EvidenceStatus.available,
        value=28.0,
        source='yfinance',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(valuation_block, "yfinance")
    pack.add_block(valuation_block)

    # Add events block
    events_block = EvidenceBlock(block_id='events')
    events_block.add_item(EvidenceItem(
        evidence_id='events_earnings',
        status=EvidenceStatus.available,
        value={'next_earnings': '2024-01-25'},
        source='yfinance',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    _fill_expected_fields(events_block, "yfinance")
    pack.add_block(events_block)

    # Add technical block
    technical_block = EvidenceBlock(block_id='technical')
    technical_block.add_item(EvidenceItem(
        evidence_id='technical_sma_20',
        status=EvidenceStatus.available,
        value=175.0,
        source='yfinance',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    pack.add_block(technical_block)

    # Add market_context block
    market_context_block = EvidenceBlock(block_id='market_context')
    market_context_block.add_item(EvidenceItem(
        evidence_id='market_phase',
        status=EvidenceStatus.available,
        value='bull',
        source='yfinance',
        as_of=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    ))
    pack.add_block(market_context_block)

    return pack


def create_degraded_evidence_pack() -> EvidencePack:
    """Create an evidence pack with degraded data quality."""
    pack = create_cn_evidence_pack()

    # 降级必须打在关键字段上：非关键字段缺失只降分，不该、也不会拦住诊断。
    if 'quote' in pack.blocks:
        for evidence_id in ("quote_price", "quote_volume"):
            pack.add_item_to_block(
                "quote",
                EvidenceItem(
                    evidence_id=evidence_id,
                    status=EvidenceStatus.missing,
                    missing_reason="Data provider unavailable",
                ),
            )

    # Add missing block
    technical_block = EvidenceBlock(block_id='technical')
    technical_block.add_item(EvidenceItem(
        evidence_id='technical_sma_20',
        status=EvidenceStatus.missing,
        missing_reason='Data provider unavailable',
    ))
    pack.add_block(technical_block)

    return pack


# Test cases for instrument normalization
INSTRUMENT_TEST_CASES = [
    # (input, market_hint, expected_symbol, expected_exchange)
    ('600519', 'CN', '600519.SH', 'SSE'),
    ('000001', 'CN', '000001.SZ', 'SZSE'),
    ('430047', 'CN', '430047.BJ', 'BSE'),
    ('AAPL', 'US', 'AAPL', 'NASDAQ'),
    ('MSFT', 'US', 'MSFT', 'NYSE'),
    ('600519.SH', 'CN', '600519.SH', 'SSE'),
    ('000001.SZ', 'CN', '000001.SZ', 'SZSE'),
]

# Test cases for quality validation
QUALITY_TEST_CASES = [
    # (market, horizon, expected_availability)
    ('CN', 'short', 'actionable'),
    ('CN', 'medium', 'actionable'),
    ('CN', 'long', 'actionable'),
    ('US', 'short', 'actionable'),
    ('US', 'medium', 'actionable'),
    ('US', 'long', 'actionable'),
]

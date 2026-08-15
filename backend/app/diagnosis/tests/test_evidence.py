"""
Unit Tests for EvidencePack and Quality Gates

Tests evidence pack creation, validation, and quality gates.
"""

import pytest
from datetime import datetime, timedelta, timezone
from ...diagnosis.evidence.schemas import (
    EVIDENCE_BLOCKS,
    EvidenceItem, EvidenceBlock, EvidencePack, EvidenceStatus, Market
)
from ...diagnosis.evidence.quality import validate_evidence_quality
from .fixtures import (
    create_cn_evidence_pack, create_us_evidence_pack,
    create_degraded_evidence_pack, CN_FIXTURES
)


class TestEvidenceItem:
    """Test cases for EvidenceItem."""

    def test_create_item(self):
        """Test creating an evidence item."""
        item = EvidenceItem(
            evidence_id='test_item',
            status=EvidenceStatus.available,
            value='test_value',
            source='test_source',
            as_of=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
        )

        assert item.evidence_id == 'test_item'
        assert item.status == EvidenceStatus.available
        assert item.value == 'test_value'

    def test_item_serialization(self):
        """Test item serialization to dict."""
        item = EvidenceItem(
            evidence_id='test_item',
            status=EvidenceStatus.available,
            value='test_value',
            source='test_source',
        )

        data = item.to_dict()
        assert data['evidence_id'] == 'test_item'
        assert data['status'] == 'available'
        assert data['value'] == 'test_value'


class TestEvidenceBlock:
    """Test cases for EvidenceBlock."""

    def test_create_block(self):
        """Test creating an evidence block."""
        block = EvidenceBlock(block_id='test_block')
        assert block.block_id == 'test_block'
        assert block.items == {}
        # Default status is missing (empty block has no data)
        assert block.status == EvidenceStatus.missing

    def test_add_item(self):
        """Test adding items to a block."""
        block = EvidenceBlock(block_id='test_block')
        item = EvidenceItem(
            evidence_id='test_item',
            status=EvidenceStatus.available,
            value='test_value',
        )

        block.add_item(item)
        assert 'test_item' in block.items
        assert block.status == EvidenceStatus.available
        assert block.completeness == 1.0

    def test_block_status_updates(self):
        """Test block status updates based on items."""
        block = EvidenceBlock(block_id='test_block')

        # Add available item
        item1 = EvidenceItem(
            evidence_id='item1',
            status=EvidenceStatus.available,
            value='value1',
        )
        block.add_item(item1)
        assert block.status == EvidenceStatus.available

        # Add partial item
        item2 = EvidenceItem(
            evidence_id='item2',
            status=EvidenceStatus.partial,
            value='value2',
        )
        block.add_item(item2)
        assert block.status == EvidenceStatus.partial

    @pytest.mark.parametrize("status", list(EvidenceStatus))
    def test_homogeneous_status_is_preserved(self, status):
        block = EvidenceBlock(block_id="test_block")
        block.add_item(EvidenceItem(evidence_id="one", status=status))
        block.add_item(EvidenceItem(evidence_id="two", status=status))

        assert block.status is status

    @pytest.mark.parametrize(
        ("statuses", "expected"),
        [
            ([EvidenceStatus.available, EvidenceStatus.missing], EvidenceStatus.partial),
            ([EvidenceStatus.fallback, EvidenceStatus.stale], EvidenceStatus.partial),
            ([EvidenceStatus.estimated, EvidenceStatus.fetch_failed], EvidenceStatus.partial),
            ([EvidenceStatus.fetch_failed, EvidenceStatus.missing], EvidenceStatus.fetch_failed),
            ([EvidenceStatus.missing, EvidenceStatus.not_supported], EvidenceStatus.missing),
        ],
    )
    def test_mixed_status_aggregation_table(self, statuses, expected):
        block = EvidenceBlock(block_id="test_block")
        for index, status in enumerate(statuses):
            block.add_item(EvidenceItem(evidence_id=str(index), status=status))

        assert block.status is expected


class TestEvidencePack:
    """Test cases for EvidencePack."""

    def test_create_pack(self):
        """Test creating an evidence pack."""
        pack = create_cn_evidence_pack()
        assert pack.instrument is not None
        assert pack.instrument.market == Market.CN
        assert len(pack.blocks) > 0

    def test_add_block(self):
        """Test adding blocks to a pack."""
        pack = EvidencePack()
        block = EvidenceBlock(block_id='test_block')
        pack.add_block(block)

        assert 'test_block' in pack.blocks

    def test_get_item(self):
        """Test getting items across blocks."""
        pack = create_cn_evidence_pack()
        item = pack.get_item('identity_name')
        assert item is not None
        assert item.value == '贵州茅台'

    def test_pack_serialization(self):
        """Test pack serialization to dict."""
        pack = create_cn_evidence_pack()
        data = pack.to_dict()

        assert 'schema_version' in data
        assert 'instrument' in data
        assert 'blocks' in data
        assert 'quality_score' in data

    def test_pack_json(self):
        """Test pack serialization to JSON."""
        pack = create_cn_evidence_pack()
        json_str = pack.to_json()

        assert isinstance(json_str, str)
        assert '600519.SH' in json_str

    def test_expected_fields_not_extra_items_define_block_score(self):
        pack = EvidencePack()
        quote = EvidenceBlock(block_id="quote")
        quote.add_item(EvidenceItem(evidence_id="quote_price", status=EvidenceStatus.available))
        pack.add_block(quote)
        one_item_score = pack.quality_score

        for index in range(20):
            pack.add_item_to_block(
                "quote",
                EvidenceItem(evidence_id=f"diagnostic_{index}", status=EvidenceStatus.available),
            )

        assert pack.quality_score == one_item_score
        assert pack.completeness == pytest.approx(0.25)

    def test_attached_block_mutation_recalculates_metrics(self):
        pack = EvidencePack()
        quote = EvidenceBlock(block_id="quote")
        pack.add_block(quote)

        quote.add_item(
            EvidenceItem(evidence_id="quote_price", status=EvidenceStatus.available),
        )

        assert pack.quality_score == pytest.approx(0.25)
        assert pack.completeness == pytest.approx(0.25)

    def test_not_supported_block_is_excluded_from_pack_metrics(self):
        pack = EvidencePack()
        quote = EvidenceBlock(block_id="quote")
        for evidence_id in EVIDENCE_BLOCKS["quote"]["expected_evidence_ids"]:
            quote.add_item(
                EvidenceItem(evidence_id=evidence_id, status=EvidenceStatus.available)
            )
        pack.add_block(quote)
        unsupported = EvidenceBlock(block_id="capital_flow")
        unsupported.add_item(
            EvidenceItem(
                evidence_id="capital_flow_net_inflow",
                status=EvidenceStatus.not_supported,
            )
        )
        pack.add_block(unsupported)

        assert pack.quality_score == 1.0
        assert pack.completeness == 1.0


class TestQualityGates:
    """Test cases for data quality gates."""

    def test_validate_actionable(self):
        """Test validation of actionable evidence pack."""
        pack = create_cn_evidence_pack()
        result = validate_evidence_quality(pack, 'CN', 'medium')

        assert result.passed is True
        assert result.availability == 'actionable'
        assert len(result.errors) == 0

    def test_validate_limited(self):
        """Test validation of limited evidence pack."""
        pack = create_degraded_evidence_pack()
        result = validate_evidence_quality(pack, 'CN', 'medium')

        # Should be limited or insufficient depending on degradation
        assert result.availability in ['limited', 'insufficient']

    def test_validate_insufficient(self):
        """Test validation of insufficient evidence pack."""
        pack = EvidencePack()  # Empty pack
        result = validate_evidence_quality(pack, 'CN', 'short')

        assert result.passed is False
        assert result.availability == 'insufficient'
        assert len(result.errors) > 0

    def test_us_market_validation(self):
        """Test validation for US market."""
        pack = create_us_evidence_pack()
        result = validate_evidence_quality(pack, 'US', 'medium')

        assert result.passed is True
        assert result.availability == 'actionable'

    def test_quality_score_in_result(self):
        """Test that quality score is included in result."""
        pack = create_cn_evidence_pack()
        result = validate_evidence_quality(pack, 'CN', 'medium')

        assert result.quality_score >= 0
        assert result.quality_score <= 1
        assert result.completeness >= 0
        assert result.completeness <= 1

    @staticmethod
    def _complete_gate_pack() -> EvidencePack:
        pack = EvidencePack(instrument=CN_FIXTURES["normal"])
        for block_id in ["identity", "quote", "fundamentals", "valuation", "events"]:
            block = EvidenceBlock(block_id=block_id)
            for evidence_id in EVIDENCE_BLOCKS[block_id]["expected_evidence_ids"]:
                block.add_item(
                    EvidenceItem(
                        evidence_id=evidence_id,
                        status=EvidenceStatus.available,
                        as_of=datetime.now(timezone.utc),
                    )
                )
            pack.add_block(block)
        return pack

    @pytest.mark.parametrize(
        "blocking_status",
        [
            EvidenceStatus.missing,
            EvidenceStatus.fetch_failed,
            EvidenceStatus.not_supported,
        ],
    )
    def test_required_block_failure_never_actionable(self, blocking_status):
        pack = self._complete_gate_pack()
        quote = EvidenceBlock(block_id="quote", status=blocking_status)
        if blocking_status is not EvidenceStatus.missing:
            quote.add_item(
                EvidenceItem(evidence_id="quote_price", status=blocking_status)
            )
        pack.add_block(quote)

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is False
        assert result.availability != "actionable"

    def test_gate_metrics_only_use_required_blocks(self):
        pack = self._complete_gate_pack()
        for index in range(20):
            block = EvidenceBlock(block_id=f"optional_{index}")
            block.add_item(
                EvidenceItem(evidence_id=f"optional_{index}", status=EvidenceStatus.missing)
            )
            pack.add_block(block)

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is True
        assert result.quality_score == 1.0
        assert result.completeness == 1.0

    def test_stale_required_evidence_blocks_actionable(self):
        pack = self._complete_gate_pack()
        stale_time = datetime.now(timezone.utc) - timedelta(days=8)
        for item in pack.blocks["quote"].items.values():
            item.as_of = stale_time

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is False
        assert result.availability != "actionable"
        assert any("stale" in error.lower() for error in result.errors)

    def test_naive_timestamps_are_interpreted_as_utc(self):
        pack = self._complete_gate_pack()
        # 取 10 天而非刚好越界的天数：本地时区与 UTC 的偏移不该让断言在一天里翻转
        for item in pack.blocks["quote"].items.values():
            item.as_of = datetime.now() - timedelta(days=10)

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is False
        assert any("stale" in error.lower() for error in result.errors)

    def test_missing_instrument_blocks_otherwise_complete_pack(self):
        pack = self._complete_gate_pack()
        pack.instrument = None

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is False
        assert result.availability != "actionable"
        assert "Missing instrument" in result.errors

    def test_required_freshness_evidence_without_timestamp_is_blocking(self):
        pack = self._complete_gate_pack()
        for item in pack.blocks["quote"].items.values():
            item.as_of = None
            item.fetched_at = None

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is False
        assert result.availability != "actionable"
        assert any("freshness timestamp" in error for error in result.errors)

    def test_optional_field_gap_warns_but_does_not_block(self):
        """免费源拿不到的字段（如 EV/EBITDA）只降分，不能把整只股票判死。"""
        pack = self._complete_gate_pack()
        pack.add_item_to_block(
            "valuation",
            EvidenceItem(
                evidence_id="valuation_ev_ebitda",
                status=EvidenceStatus.missing,
                missing_reason="免费数据源未提供企业价值/EBITDA",
            ),
        )

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is True
        assert result.availability == "actionable"
        assert any("valuation_ev_ebitda" in warning for warning in result.warnings)

    def test_critical_field_gap_blocks(self):
        """没有价格就没有结论——关键字段缺失必须拦下。"""
        pack = self._complete_gate_pack()
        del pack.blocks["quote"].items["quote_price"]

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is False
        assert any("quote_price" in error for error in result.errors)

    def test_events_are_not_judged_by_price_freshness(self):
        """分红/披露天然是几个月前的事实，不能用行情的时钟去量。"""
        pack = self._complete_gate_pack()
        for item in pack.blocks["events"].items.values():
            item.as_of = datetime.now(timezone.utc) - timedelta(days=200)

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is True
        assert not any("stale" in error.lower() for error in result.errors)

    def test_absent_corporate_action_is_not_a_data_gap(self):
        """从不送转的公司（如茅台）没有 events_splits，这是事实而非缺数据。"""
        pack = self._complete_gate_pack()
        del pack.blocks["events"].items["events_splits"]

        result = validate_evidence_quality(pack, "CN", "medium")

        assert result.passed is True


class TestEdgeCases:
    """Test edge cases for evidence and quality."""

    def test_empty_evidence_pack(self):
        """Test empty evidence pack."""
        pack = EvidencePack()
        assert pack.quality_score == 0.0
        assert pack.completeness == 0.0

    def test_missing_instrument(self):
        """Test evidence pack without instrument."""
        pack = EvidencePack()
        block = EvidenceBlock(block_id='test')
        pack.add_block(block)

        result = validate_evidence_quality(pack, 'CN', 'short')
        assert 'Missing instrument' in result.errors or result.passed is False

    def test_invalid_market(self):
        """Test validation with invalid market."""
        pack = create_cn_evidence_pack()
        result = validate_evidence_quality(pack, 'INVALID', 'short')

        assert result.passed is False
        assert len(result.errors) > 0

"""
Phase 1 测试

测试诊断模型、EvidencePack builder、版本身份和确定性摘要。
"""

import asyncio
import copy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from ..evidence.schemas import (
    EvidenceBlock, EvidenceItem, EvidencePack, EvidenceStatus, Horizon,
)
from ..dimensions.base import DimensionOpinion
from ..schemas import (
    DecisionProfileSchema,
    DiagnosisFileCreateRequest,
    DiagnosisRunResponse,
    DimensionOpinionSchema,
    InstrumentSchema,
    PositionType,
    QualityGateResultSchema,
)
from ..version import (
    AnalysisManifest,
    ExecutionProvenance,
    generate_analysis_version,
    generate_result_identity,
    hash_decision_profile,
    hash_evidence_pack,
)
from ..summary import create_deterministic_summary
from .fixtures import CN_FIXTURES, create_cn_evidence_pack, create_us_evidence_pack


class TestEvidencePackBuilder:
    """测试 EvidencePack Builder"""

    def test_builder_creation(self):
        """测试构建器创建"""
        from ..evidence.builder import EvidencePackBuilder
        builder = EvidencePackBuilder(
            instrument=CN_FIXTURES['normal'],
            market='CN'
        )
        assert builder.instrument is not None
        assert builder.market == 'CN'

    def test_builder_with_providers(self):
        """测试带 provider 的构建器"""
        from ..evidence.builder import create_evidence_pack_builder
        builder = create_evidence_pack_builder(CN_FIXTURES['normal'])
        assert builder is not None
        assert 'quote' in builder._providers

    def test_fallback_marks_items_and_records_all_attempts(self):
        from ..evidence.builder import EvidencePackBuilder

        async def primary(_instrument):
            raise RuntimeError("primary down")

        async def secondary(_instrument):
            return [
                EvidenceItem(
                    evidence_id="quote_price",
                    status=EvidenceStatus.available,
                    value=100,
                    source="secondary-source",
                )
            ]

        builder = EvidencePackBuilder(CN_FIXTURES["normal"], "CN")
        builder.register_provider_chain("quote", [primary, secondary])

        pack = asyncio.run(builder.fetch_evidence(["quote"]))

        item = pack.get_item("quote_price")
        assert item is not None
        assert item.status is EvidenceStatus.fallback
        assert item.source == "secondary-source"
        assert item.fallback_from == "primary"
        assert [attempt["status"] for attempt in pack.provider_attempts] == [
            "failed",
            "success",
        ]
        assert [attempt["block_id"] for attempt in pack.provider_attempts] == [
            "quote",
            "quote",
        ]
        assert [attempt["attempt_number"] for attempt in pack.provider_attempts] == [1, 2]

    def test_registered_provider_returning_no_data_is_missing(self):
        from ..evidence.builder import EvidencePackBuilder

        async def empty_provider(_instrument):
            return []

        builder = EvidencePackBuilder(CN_FIXTURES["normal"], "CN")
        builder.register_provider_chain("quote", [empty_provider])

        pack = asyncio.run(builder.fetch_evidence(["quote"]))

        assert pack.blocks["quote"].status is EvidenceStatus.missing

    def test_unconfigured_provider_is_not_not_supported(self):
        from ..evidence.builder import EvidencePackBuilder

        builder = EvidencePackBuilder(CN_FIXTURES["normal"], "CN")
        pack = asyncio.run(builder.fetch_evidence(["quote"]))

        assert pack.blocks["quote"].status is EvidenceStatus.missing
        assert "provider_unconfigured:quote" in pack.warnings

    def test_explicit_unsupported_capability_is_not_provider_unconfigured(self):
        from ..evidence.builder import EvidencePackBuilder

        builder = EvidencePackBuilder(CN_FIXTURES["normal"], "CN")
        builder.mark_not_supported("capital_flow")

        pack = asyncio.run(builder.fetch_evidence(["capital_flow"]))

        assert pack.blocks["capital_flow"].status is EvidenceStatus.not_supported
        assert "provider_unconfigured:capital_flow" not in pack.warnings

    def test_unexpected_fetch_task_failure_is_surfaced(self):
        from ..evidence.builder import EvidencePackBuilder

        class BrokenBuilder(EvidencePackBuilder):
            async def _fetch_block(self, block_id):
                raise AssertionError(f"broken:{block_id}")

        builder = BrokenBuilder(CN_FIXTURES["normal"], "CN")

        with pytest.raises(AssertionError, match="broken:quote"):
            asyncio.run(builder.fetch_evidence(["quote"]))

    def test_manual_add_item_keeps_pack_metrics_synchronized(self):
        from ..evidence.builder import EvidencePackBuilder

        builder = EvidencePackBuilder(CN_FIXTURES["normal"], "CN")
        builder.add_item(
            "quote",
            EvidenceItem(evidence_id="quote_price", status=EvidenceStatus.available),
        )

        assert builder.pack.quality_score == pytest.approx(0.25)
        assert builder.pack.completeness == pytest.approx(0.25)


class TestVersionIdentity:
    """测试版本身份生成"""

    def test_hash_evidence_pack(self):
        """测试 EvidencePack 哈希"""
        pack = create_cn_evidence_pack()
        hash1 = hash_evidence_pack(pack)
        hash2 = hash_evidence_pack(pack)
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_hash_decision_profile(self):
        """测试 DecisionProfile 哈希"""
        profile = DecisionProfileSchema()
        hash1 = hash_decision_profile(profile)
        hash2 = hash_decision_profile(profile)
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_generate_analysis_version(self):
        """测试版本指纹生成"""
        version = generate_analysis_version(self._manifest())
        assert len(version) == 64  # SHA256 hex digest

    def test_version_deterministic(self):
        """测试版本指纹确定性"""
        manifest = self._manifest()
        v1 = generate_analysis_version(manifest)
        v2 = generate_analysis_version(manifest)
        assert v1 == v2

    def test_method_version_does_not_change_with_data(self):
        pack1 = create_cn_evidence_pack()
        pack2 = create_us_evidence_pack()
        profile = DecisionProfileSchema()
        manifest = self._manifest()

        assert generate_analysis_version(manifest) == generate_analysis_version(manifest)
        assert generate_result_identity(manifest, pack1, profile, "fresh-v1") != (
            generate_result_identity(manifest, pack2, profile, "fresh-v1")
        )

    def test_fetch_timestamp_does_not_change_evidence_hash(self):
        pack = create_cn_evidence_pack()
        changed = copy.deepcopy(pack)
        changed.fetched_at = pack.fetched_at + timedelta(hours=1)
        for block in changed.blocks.values():
            for item in block.items.values():
                if item.fetched_at:
                    item.fetched_at += timedelta(hours=1)

        assert hash_evidence_pack(pack) == hash_evidence_pack(changed)

    @pytest.mark.parametrize(
        ("field", "replacement"),
        [
            ("schema_version", "2"),
            ("normalization_version", "2"),
            ("indicator_registry_version", "2"),
            ("dimension_registry_version", "2"),
            ("prompt_version", "2"),
            ("model_contract_version", "2"),
            ("conflict_rules_version", "2"),
            ("quality_rules_version", "2"),
            ("risk_rules_version", "2"),
            ("action_mapping_version", "2"),
        ],
    )
    def test_each_manifest_factor_invalidates_method_identity(self, field, replacement):
        manifest = self._manifest()

        assert generate_analysis_version(manifest) != generate_analysis_version(
            replace(manifest, **{field: replacement})
        )

    def test_manifest_requires_every_method_version(self):
        with pytest.raises(TypeError):
            AnalysisManifest()

    def test_manifest_rejects_blank_method_version(self):
        with pytest.raises(ValueError, match="non-empty"):
            replace(self._manifest(), prompt_version="   ")

    def test_execution_provenance_keeps_exact_runtime_identity(self):
        provenance = ExecutionProvenance(
            actual_model_id="gpt-5.4-2026-08-01",
            endpoint="https://example.invalid/v1",
            parameters={"temperature": 0.1},
            actual_providers={"quote": "secondary"},
        )

        assert provenance.to_dict()["actual_model_id"] == "gpt-5.4-2026-08-01"

    @pytest.mark.parametrize(
        ("field", "replacement"),
        [
            ("evidence_id", "semantic-2"),
            ("status", EvidenceStatus.partial),
            ("value", 999),
            ("source", "secondary"),
            ("source_record_id", "record-2"),
            ("as_of", datetime(2026, 1, 2)),
            ("currency", "USD"),
            ("unit", "shares"),
            ("period", "FY2025"),
            ("fallback_from", "primary"),
            ("missing_reason", "not published"),
            ("warnings", ["estimated"]),
        ],
    )
    def test_each_semantic_evidence_field_invalidates_hash(self, field, replacement):
        pack = EvidencePack()
        pack.add_block(EvidenceBlock(block_id="custom"))
        pack.add_item_to_block(
            "custom",
            EvidenceItem(
                evidence_id="semantic",
                status=EvidenceStatus.available,
                value=1,
                source="primary",
                source_record_id="record-1",
                as_of=datetime(2026, 1, 1),
                currency="CNY",
                unit="yuan",
                period="FY2024",
            ),
        )
        changed = copy.deepcopy(pack)
        setattr(changed.get_item("semantic"), field, replacement)

        assert hash_evidence_pack(pack) != hash_evidence_pack(changed)

    @staticmethod
    def _manifest() -> AnalysisManifest:
        return AnalysisManifest(
            schema_version="1",
            normalization_version="1",
            indicator_registry_version="1",
            dimension_registry_version="1",
            prompt_version="1",
            model_contract_version="1",
            conflict_rules_version="1",
            quality_rules_version="1",
            risk_rules_version="1",
            action_mapping_version="1",
        )


class TestDomainContracts:
    def test_holding_requires_portfolio_weight(self):
        with pytest.raises(ValidationError):
            DecisionProfileSchema(position_status=PositionType.HOLDING)

    @pytest.mark.parametrize("field", ["portfolio_weight", "cost_basis", "entry_date"])
    def test_empty_position_rejects_holding_only_fields(self, field):
        value = datetime.now().date() if field == "entry_date" else 0.1
        with pytest.raises(ValidationError):
            DecisionProfileSchema(position_status=PositionType.EMPTY, **{field: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [("primary_horizon", "intraday"), ("risk_tolerance", "reckless")],
    )
    def test_profile_rejects_unknown_enum_values(self, field, value):
        with pytest.raises(ValidationError):
            DecisionProfileSchema(**{field: value})

    def test_target_weight_cannot_exceed_maximum(self):
        with pytest.raises(ValidationError):
            DecisionProfileSchema(
                target_position_weight=0.4,
                max_position_weight=0.3,
            )

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "unavailable", "direction": "neutral"},
            {"status": "failed", "direction": "bearish"},
            {"status": "success", "direction": None},
            {"status": "degraded", "direction": "bullish", "warnings": []},
        ],
    )
    def test_dimension_opinion_rejects_invalid_status_direction_pairs(self, payload):
        with pytest.raises(ValidationError):
            DimensionOpinionSchema(
                dimension_id="valuation",
                horizon="medium",
                confidence=0.5,
                **payload,
            )

    def test_domain_opinion_does_not_let_unavailable_vote_neutral(self):
        with pytest.raises(ValueError, match="cannot vote"):
            DimensionOpinion(
                dimension_id="valuation",
                horizon=Horizon.medium,
                status="unavailable",
                direction="neutral",
            )

    def test_domain_degraded_opinion_requires_warning(self):
        with pytest.raises(ValueError, match="warning"):
            DimensionOpinion(
                dimension_id="valuation",
                horizon=Horizon.medium,
                status="degraded",
                direction="bullish",
            )

    @pytest.mark.parametrize("market", ["EU", "", "cn"])
    def test_instrument_schema_rejects_unknown_market(self, market):
        with pytest.raises(ValidationError):
            InstrumentSchema(market=market, canonical_symbol="TEST")

    def test_file_request_rejects_unknown_market_hint(self):
        with pytest.raises(ValidationError):
            DiagnosisFileCreateRequest(symbol="TEST", market_hint="EU")

    @pytest.mark.parametrize(
        ("field", "value"),
        [("status", "retrying"), ("progress", -1), ("progress", 101)],
    )
    def test_run_response_rejects_invalid_status_and_progress(self, field, value):
        payload = {
            "id": "run-1",
            "status": "pending",
            "stage": "queued",
            "progress": 0,
            "created_at": datetime(2026, 1, 1),
        }
        payload[field] = value
        with pytest.raises(ValidationError):
            DiagnosisRunResponse(**payload)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("availability", "unknown"),
            ("quality_score", -0.1),
            ("quality_score", 1.1),
            ("completeness", -0.1),
            ("completeness", 1.1),
        ],
    )
    def test_quality_gate_response_rejects_invalid_ranges(self, field, value):
        payload = {
            "passed": False,
            "availability": "insufficient",
            "quality_score": 0.0,
            "completeness": 0.0,
        }
        payload[field] = value
        with pytest.raises(ValidationError):
            QualityGateResultSchema(**payload)


class TestDeterministicSummary:
    """测试确定性摘要"""

    def test_insufficient_summary(self):
        """测试 insufficient 摘要"""
        pack = EvidencePack()  # 空包
        profile = DecisionProfileSchema()
        summary = create_deterministic_summary(pack, profile)

        assert summary['availability'] == 'insufficient'
        assert summary['action'] is None
        assert summary['confidence'] is None

    def test_limited_summary(self):
        """测试 limited 摘要"""
        pack = create_cn_evidence_pack()
        profile = DecisionProfileSchema()
        summary = create_deterministic_summary(pack, profile)

        # 应该是 actionable 或 limited
        assert summary['availability'] in ['actionable', 'limited']

    def test_actionable_summary(self):
        """测试 actionable 摘要"""
        pack = create_cn_evidence_pack()
        profile = DecisionProfileSchema(
            position_status=PositionType.EMPTY,
            primary_horizon='medium',
        )
        summary = create_deterministic_summary(pack, profile)

        assert summary['availability'] == 'actionable'
        assert summary['action'] is not None
        assert summary['confidence'] is not None

    def test_empty_position_uses_empty_action_set(self):
        pack = create_cn_evidence_pack()
        profile = DecisionProfileSchema(position_status=PositionType.EMPTY)

        summary = create_deterministic_summary(pack, profile)

        assert summary["availability"] == "actionable"
        assert summary["action"] == "watch"

    def test_empty_position_limited_summary_uses_watch(self, monkeypatch):
        from ..evidence.quality import QualityGateResult
        from ..summary import DeterministicSummary

        pack = create_cn_evidence_pack()
        profile = DecisionProfileSchema(position_status=PositionType.EMPTY)
        generator = DeterministicSummary(pack, profile)
        limited = QualityGateResult(
            passed=False,
            availability="limited",
            errors=["degraded"],
            warnings=[],
            quality_score=0.5,
            completeness=0.5,
        )
        monkeypatch.setattr(
            "app.diagnosis.summary.validate_evidence_quality",
            lambda *_args, **_kwargs: limited,
        )

        assert generator.generate()["action"] == "watch"

    def test_summary_has_required_fields(self):
        """测试摘要包含必要字段"""
        pack = create_cn_evidence_pack()
        profile = DecisionProfileSchema()
        summary = create_deterministic_summary(pack, profile)

        required_fields = [
            'availability', 'action', 'confidence', 'reasoning',
            'quality_score', 'completeness', 'errors', 'warnings',
            'missing_blocks', 'recommendation',
        ]
        for field in required_fields:
            assert field in summary, f"Missing field: {field}"


class TestImmutability:
    """测试不可变性"""

    def test_version_create_validation(self):
        """测试版本创建验证"""
        from ..version import ImmutabilityGuard

        guard = ImmutabilityGuard()
        existing = [
            {'diagnosis_file_id': 'file1', 'version_number': 1},
        ]
        new_version = {
            'diagnosis_file_id': 'file1',
            'version_number': 2,
        }

        is_valid, error = guard.validate_create(existing, new_version)
        assert is_valid is True

    def test_version_create_duplicate(self):
        """测试版本创建重复验证"""
        from ..version import ImmutabilityGuard

        guard = ImmutabilityGuard()
        existing = [
            {'diagnosis_file_id': 'file1', 'version_number': 1},
        ]
        new_version = {
            'diagnosis_file_id': 'file1',
            'version_number': 1,  # 重复
        }

        is_valid, error = guard.validate_create(existing, new_version)
        assert is_valid is False
        assert 'already exists' in error

    def test_version_modify_blocked(self):
        """测试版本修改被阻止"""
        from ..version import ImmutabilityGuard

        guard = ImmutabilityGuard()
        existing_version = {'id': 'v1'}
        modifications = {'action': 'buy'}

        is_valid, error = guard.validate_modify(existing_version, modifications)
        assert is_valid is False
        assert 'immutable' in error.lower()

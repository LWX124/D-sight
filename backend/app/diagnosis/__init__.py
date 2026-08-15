"""
Stock Diagnosis Module

契约层与确定性编排层。本模块尚未挂载到应用（无 API 路由）——
持久化与用户可见能力在决策漏斗 Phase 3 建设，见
`.trellis/tasks/08-14-decision-funnel-master/prd.md`。

组成：
- instrument / evidence / indicators / dimensions：证据获取与确定性分析
- conflict / quality_gate / provenance / version / summary：契约与门禁
- runner：编排链（证据 → 指标 → 维度 → 冲突 → 风险约束 → 结论）
- monitor / diff：失效条件检测与版本比对（Phase 3 接入调度）
- models：DiagnosisFile / DiagnosisVersion / DiagnosisRun 三表 ORM
"""

from .instrument import InstrumentRegistry, normalize_symbol
from .evidence.schemas import (
    EvidenceItem, EvidenceBlock, EvidencePack, EvidenceStatus,
    Instrument, Market, Horizon
)
from .evidence.quality import DataQualityGates, validate_evidence_quality
from .evidence.builder import EvidencePackBuilder, create_evidence_pack_builder
from .version import generate_analysis_version, ImmutabilityGuard, AnalysisManifest, ExecutionProvenance
from .summary import create_deterministic_summary
from .schemas import (
    DiagnosisFileCreateRequest,
    DiagnosisFileResponse,
    DiagnosisVersionResponse,
    DiagnosisRunCreateRequest,
    DiagnosisRunResponse,
    DecisionProfileSchema,
    PositionType,
    InstrumentSchema,
)
from .indicators import (
    IndicatorCalculator, IndicatorResult,
    calculate_all_indicators, INDICATOR_CALCULATORS,
)
from .dimensions import (
    DimensionAnalyzer, DimensionOpinion,
    analyze_all_dimensions, DIMENSION_ANALYZERS,
)
from .conflict import ConflictDetector, ConflictReview
from .quality_gate import QualityGate, RiskConstraint, QualityGateResult
from .provenance import ProvenanceRecord
from .runner import DiagnosisRunner, DiagnosisConclusion, DiagnosisAdvice
from .monitor import Monitor, MonitorType, UpdateMonitorResult, check_all_monitors
from .diff import DiffEngine, VersionDiff

__all__ = [
    # 标的识别
    'InstrumentRegistry',
    'normalize_symbol',
    # 证据契约
    'EvidenceItem',
    'EvidenceBlock',
    'EvidencePack',
    'EvidenceStatus',
    'Instrument',
    'Market',
    'Horizon',
    'DataQualityGates',
    'validate_evidence_quality',
    'EvidencePackBuilder',
    'create_evidence_pack_builder',
    # 版本与溯源
    'generate_analysis_version',
    'ImmutabilityGuard',
    'AnalysisManifest',
    'ExecutionProvenance',
    'ProvenanceRecord',
    'create_deterministic_summary',
    # 请求/响应 schema
    'DiagnosisFileCreateRequest',
    'DiagnosisFileResponse',
    'DiagnosisVersionResponse',
    'DiagnosisRunCreateRequest',
    'DiagnosisRunResponse',
    'DecisionProfileSchema',
    'PositionType',
    'InstrumentSchema',
    # 确定性分析
    'IndicatorCalculator',
    'IndicatorResult',
    'calculate_all_indicators',
    'INDICATOR_CALCULATORS',
    'DimensionAnalyzer',
    'DimensionOpinion',
    'analyze_all_dimensions',
    'DIMENSION_ANALYZERS',
    'ConflictDetector',
    'ConflictReview',
    'QualityGate',
    'RiskConstraint',
    'QualityGateResult',
    # 编排
    'DiagnosisRunner',
    'DiagnosisConclusion',
    'DiagnosisAdvice',
    # 更新监控与版本比对
    'Monitor',
    'MonitorType',
    'UpdateMonitorResult',
    'check_all_monitors',
    'DiffEngine',
    'VersionDiff',
]

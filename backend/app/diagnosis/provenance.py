"""
Provenance Tracker

记录模型、prompt、provider、token、耗时和规则版本。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ProvenanceRecord:
    """溯源记录"""
    # 模型信息
    model_id: Optional[str] = None
    model_family: Optional[str] = None
    model_tier: Optional[str] = None
    prompt_version: Optional[str] = None

    # Provider 信息
    providers_used: list[str] = field(default_factory=list)
    provider_latency: dict[str, float] = field(default_factory=dict)

    # Token 使用
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    # 耗时
    total_latency_ms: float = 0.0
    indicator_latency_ms: float = 0.0
    dimension_latency_ms: float = 0.0

    # 规则版本
    rule_version: str = "1.0"
    schema_version: str = "1.0"

    # 时间戳
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'model_id': self.model_id,
            'model_family': self.model_family,
            'model_tier': self.model_tier,
            'prompt_version': self.prompt_version,
            'providers_used': self.providers_used,
            'provider_latency': self.provider_latency,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'total_latency_ms': self.total_latency_ms,
            'indicator_latency_ms': self.indicator_latency_ms,
            'dimension_latency_ms': self.dimension_latency_ms,
            'rule_version': self.rule_version,
            'schema_version': self.schema_version,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }

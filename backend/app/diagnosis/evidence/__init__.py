"""
Evidence Module for Stock Diagnosis

Provides evidence schemas, quality gates, and validation.
"""

from .schemas import (
    EvidenceItem, EvidenceBlock, EvidencePack, EvidenceStatus,
    Instrument, Market, Horizon, REQUIRED_BLOCKS, EVIDENCE_BLOCKS
)
from .quality import DataQualityGates, validate_evidence_quality, QUALITY_GATES

__all__ = [
    'EvidenceItem',
    'EvidenceBlock',
    'EvidencePack',
    'EvidenceStatus',
    'Instrument',
    'Market',
    'Horizon',
    'REQUIRED_BLOCKS',
    'EVIDENCE_BLOCKS',
    'DataQualityGates',
    'validate_evidence_quality',
    'QUALITY_GATES',
]

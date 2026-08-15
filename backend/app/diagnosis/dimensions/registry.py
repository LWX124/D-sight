"""
Dimension Registry

维度注册表，管理所有维度分析器。
"""

from .base import DimensionAnalyzer
from .business_quality import BusinessQualityAnalyzer
from .financial_quality import FinancialQualityAnalyzer
from .valuation import ValuationAnalyzer
from .technical import TechnicalAnalyzer
from .events_sentiment import EventsSentimentAnalyzer
from .market_structure import MarketStructureAnalyzer


# 注册所有维度分析器
DIMENSION_ANALYZERS: dict[str, DimensionAnalyzer] = {
    'business_quality': BusinessQualityAnalyzer(),
    'financial_quality': FinancialQualityAnalyzer(),
    'valuation': ValuationAnalyzer(),
    'technical': TechnicalAnalyzer(),
    'events_and_sentiment': EventsSentimentAnalyzer(),
    'market_structure': MarketStructureAnalyzer(),
}


def get_analyzer(dimension_id: str) -> DimensionAnalyzer | None:
    """获取指定维度的分析器"""
    return DIMENSION_ANALYZERS.get(dimension_id)


def analyze_all_dimensions(evidence_pack, indicators, horizon) -> list:
    """分析所有维度"""
    results = []
    for dim_id, analyzer in DIMENSION_ANALYZERS.items():
        opinion = analyzer.analyze(evidence_pack, indicators, horizon)
        results.append(opinion)
    return results

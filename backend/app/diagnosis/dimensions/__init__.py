"""
Six-Dimension Opinion Generator

六维度意见生成模块。
"""

from .base import DimensionAnalyzer, DimensionOpinion
from .business_quality import BusinessQualityAnalyzer
from .financial_quality import FinancialQualityAnalyzer
from .valuation import ValuationAnalyzer
from .technical import TechnicalAnalyzer
from .events_sentiment import EventsSentimentAnalyzer
from .market_structure import MarketStructureAnalyzer
from .registry import DIMENSION_ANALYZERS, get_analyzer, analyze_all_dimensions

__all__ = [
    'DimensionAnalyzer',
    'DimensionOpinion',
    'BusinessQualityAnalyzer',
    'FinancialQualityAnalyzer',
    'ValuationAnalyzer',
    'TechnicalAnalyzer',
    'EventsSentimentAnalyzer',
    'MarketStructureAnalyzer',
    'DIMENSION_ANALYZERS',
    'get_analyzer',
    'analyze_all_dimensions',
]

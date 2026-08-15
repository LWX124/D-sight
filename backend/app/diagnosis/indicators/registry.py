"""
Indicator Registry

指标注册表，管理所有指标计算器。
"""

from .base import IndicatorCalculator
from .financial import FinancialIndicatorCalculator
from .valuation import ValuationIndicatorCalculator
from .technical import TechnicalIndicatorCalculator
from .risk import RiskIndicatorCalculator


# 注册所有指标计算器
INDICATOR_CALCULATORS: dict[str, IndicatorCalculator] = {
    'financial': FinancialIndicatorCalculator(),
    'valuation': ValuationIndicatorCalculator(),
    'technical': TechnicalIndicatorCalculator(),
    'risk': RiskIndicatorCalculator(),
}


def get_calculator(category: str) -> IndicatorCalculator | None:
    """获取指定类别的指标计算器"""
    return INDICATOR_CALCULATORS.get(category)


def calculate_all_indicators(evidence_pack) -> dict:
    """计算所有指标"""
    results = {}
    for category, calculator in INDICATOR_CALCULATORS.items():
        results.update(calculator.calculate(evidence_pack))
    return results

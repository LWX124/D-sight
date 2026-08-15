"""
Monitor Registry

监控注册表。
"""

from .base import Monitor
from .earnings import EarningsMonitor
from .events import EventMonitor
from .invalidation import InvalidationMonitor
from .expiry import DataExpiryMonitor


# 注册所有监控器
MONITORS: list[Monitor] = [
    EarningsMonitor(),
    EventMonitor(),
    InvalidationMonitor(),
    DataExpiryMonitor(),
]


def check_all_monitors(
    symbol: str,
    market: str,
    diagnosis_data: dict,
) -> list:
    """运行所有监控器"""
    results = []
    for monitor in MONITORS:
        result = monitor.check(symbol, market, diagnosis_data)
        if result:
            results.append(result)
    return results

"""
Monitor Base Class

监控基类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from enum import Enum


class MonitorType(Enum):
    """监控类型"""
    EARNINGS = "earnings"          # 新财报
    EVENT = "event"                # 重大事件
    INVALIDATION = "invalidation"  # 失效条件
    DATA_EXPIRY = "data_expiry"    # 数据过期


@dataclass
class UpdateMonitorResult:
    """监控结果"""
    monitor_type: MonitorType
    symbol: str
    market: str
    priority: str  # high / medium / low
    reason: str
    triggering_conditions: list[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'monitor_type': self.monitor_type.value,
            'symbol': self.symbol,
            'market': self.market,
            'priority': self.priority,
            'reason': self.reason,
            'triggering_conditions': self.triggering_conditions,
            'detected_at': self.detected_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }


class Monitor(ABC):
    """监控器基类"""
    monitor_type: MonitorType = MonitorType.EVENT

    @abstractmethod
    def check(
        self,
        symbol: str,
        market: str,
        diagnosis_data: dict,
    ) -> Optional[UpdateMonitorResult]:
        """
        检查是否需要更新

        Args:
            symbol: 股票代码
            market: 市场
            diagnosis_data: 诊断数据

        Returns:
            监控结果，如果不需要更新则返回 None
        """
        pass

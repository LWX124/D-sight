"""
Data Expiry Monitor

数据过期监控。
"""

from datetime import datetime, timezone
from typing import Optional

from .base import Monitor, MonitorType, UpdateMonitorResult


class DataExpiryMonitor(Monitor):
    """数据过期监控器"""
    monitor_type = MonitorType.DATA_EXPIRY

    def __init__(self, max_age_hours: float = 48):
        """
        Args:
            max_age_hours: 最大数据年龄（小时）
        """
        self.max_age_hours = max_age_hours

    def check(
        self,
        symbol: str,
        market: str,
        diagnosis_data: dict,
    ) -> Optional[UpdateMonitorResult]:
        """检查是否需要更新"""
        fetched_at = diagnosis_data.get('fetched_at')
        if not fetched_at:
            return None

        try:
            fetch_time = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            age_hours = (now - fetch_time).total_seconds() / 3600

            if age_hours > self.max_age_hours:
                return UpdateMonitorResult(
                    monitor_type=MonitorType.DATA_EXPIRY,
                    symbol=symbol,
                    market=market,
                    priority='medium',
                    reason=f"数据已过期 {age_hours:.1f} 小时（阈值 {self.max_age_hours} 小时）",
                    triggering_conditions=[
                        f"数据获取时间: {fetched_at}",
                        f"数据年龄: {age_hours:.1f} 小时",
                    ],
                )
        except (ValueError, TypeError):
            pass

        return None

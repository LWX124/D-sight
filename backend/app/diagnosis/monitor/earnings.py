"""
Earnings Monitor

财报监控。
"""

from datetime import datetime, timezone
from typing import Optional

from .base import Monitor, MonitorType, UpdateMonitorResult


class EarningsMonitor(Monitor):
    """财报监控器"""
    monitor_type = MonitorType.EARNINGS

    def __init__(self, reminder_days: int = 7):
        """
        Args:
            reminder_days: 提前提醒天数
        """
        self.reminder_days = reminder_days

    def check(
        self,
        symbol: str,
        market: str,
        diagnosis_data: dict,
    ) -> Optional[UpdateMonitorResult]:
        """检查是否需要更新"""
        # 获取下一个财报日期
        earnings_dates = diagnosis_data.get('earnings_dates', [])
        if not earnings_dates:
            return None

        now = datetime.now(timezone.utc)

        for date_str in earnings_dates:
            try:
                earnings_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                days_until = (earnings_date - now).days

                if 0 <= days_until <= self.reminder_days:
                    return UpdateMonitorResult(
                        monitor_type=MonitorType.EARNINGS,
                        symbol=symbol,
                        market=market,
                        priority='high' if days_until <= 3 else 'medium',
                        reason=f"财报将于 {days_until} 天后发布",
                        triggering_conditions=[
                            f"财报日期: {date_str}",
                            f"距今天数: {days_until}",
                        ],
                        expires_at=earnings_date,
                    )
            except (ValueError, TypeError):
                continue

        return None

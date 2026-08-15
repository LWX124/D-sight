"""
Event Monitor

重大事件监控。
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from .base import Monitor, MonitorType, UpdateMonitorResult


class EventMonitor(Monitor):
    """事件监控器"""
    monitor_type = MonitorType.EVENT

    def __init__(self, lookback_days: int = 7):
        """
        Args:
            lookback_days: 回溯天数
        """
        self.lookback_days = lookback_days

    def check(
        self,
        symbol: str,
        market: str,
        diagnosis_data: dict,
    ) -> Optional[UpdateMonitorResult]:
        """检查是否需要更新"""
        events = diagnosis_data.get('recent_events', [])
        if not events:
            return None

        now = datetime.now(timezone.utc)
        lookback = timedelta(days=self.lookback_days)

        # 检查重大事件
        significant_events = []
        for event in events:
            try:
                event_date = datetime.fromisoformat(event.get('date', '').replace('Z', '+00:00'))
                if now - event_date <= lookback:
                    # 检查是否为重大事件
                    if event.get('significance') in ('high', 'critical'):
                        significant_events.append(event)
            except (ValueError, TypeError):
                continue

        if significant_events:
            event_types = [e.get('type', 'unknown') for e in significant_events]
            return UpdateMonitorResult(
                monitor_type=MonitorType.EVENT,
                symbol=symbol,
                market=market,
                priority='high' if any(e.get('significance') == 'critical' for e in significant_events) else 'medium',
                reason=f"检测到 {len(significant_events)} 个重大事件",
                triggering_conditions=[
                    f"事件类型: {', '.join(event_types)}",
                ],
            )

        return None

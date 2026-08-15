"""A 股取数层。

diagnosis（个股诊断）、板块热度、策略筛选三方共用；独立于 diagnosis，
不依赖任何 diagnosis 契约，只输出带 `as_of` + `source` 的 DataPoint。

设计约束（见 `.trellis/tasks/08-14-phase0-foundation/design.md` D2）：
- 每个返回值必带 `as_of` 与 `source`；取不到就抛类型化异常，**任何路径不得返回默认假数**
- 只支持 A 股；market != CN 一律 `MarketNotSupported`
- akshare 无 SLA：限频 + 重试 + 异常归一在 `akshare_client` 统一处理
"""

from .errors import (
    DataIncomplete,
    MarketDataError,
    MarketNotSupported,
    SymbolNotFound,
    UpstreamUnavailable,
)
from .events import get_events
from .financials import get_financials
from .profile import get_profile
from .quotes import get_daily_bars, get_daily_bars_em, get_quote, latest_quote
from .schemas import Bar, DailyBars, DataPoint, PointSet
from .symbols import CN_MARKET, normalize_cn_code, to_sina_symbol
from .technical import compute_technicals
from .valuation import get_valuation

__all__ = [
    # 契约
    "DataPoint",
    "PointSet",
    "Bar",
    "DailyBars",
    # 异常
    "MarketDataError",
    "MarketNotSupported",
    "SymbolNotFound",
    "UpstreamUnavailable",
    "DataIncomplete",
    # 取数
    "get_daily_bars",
    "get_daily_bars_em",
    "get_quote",
    "latest_quote",
    "get_financials",
    "get_valuation",
    "get_profile",
    "get_events",
    "compute_technicals",
    # 代码归一
    "CN_MARKET",
    "normalize_cn_code",
    "to_sina_symbol",
]

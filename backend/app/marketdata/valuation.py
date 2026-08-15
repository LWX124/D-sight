"""估值：PE(TTM)/PE(静)/PB/PS/PEG/市值，以及历史分位。

源：东财 `stock_value_em`（datacenter 域，本环境可用）。该接口一次返回全历史
（约 8 年日频），因此历史分位由真实序列计算，而非估算。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import akshare as ak
import pandas as pd

from .akshare_client import fetch_df
from .errors import DataIncomplete, MarketNotSupported
from .schemas import DataPoint, PointSet
from .symbols import CN_MARKET, normalize_cn_code

SOURCE_VALUE_EM = "akshare:stock_value_em"
SOURCE_BAIDU = "akshare:stock_zh_valuation_baidu"

# 东财列名 → 内部 key、单位
_COLUMN_MAP: dict[str, tuple[str, Optional[str]]] = {
    "PE(TTM)": ("valuation_pe", "x"),
    "PE(静)": ("valuation_pe_static", "x"),
    "市净率": ("valuation_pb", "x"),
    "市销率": ("valuation_ps", "x"),
    "PEG值": ("valuation_peg", "x"),
    "市现率": ("valuation_pcf", "x"),
    "总市值": ("quote_market_cap", "CNY"),
    "流通市值": ("quote_float_market_cap", "CNY"),
}

# 分位数窗口：近 5 年（按 244 交易日/年）
_PERCENTILE_WINDOW = 244 * 5


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _percentile(series: pd.Series, current: float) -> Optional[float]:
    """当前值在历史序列中的分位（0-100）。仅用正值样本，PE 为负无意义。"""
    clean = series.dropna()
    clean = clean[clean > 0]
    if len(clean) < 60 or current is None or current <= 0:
        return None
    return round(float((clean <= current).sum()) / len(clean) * 100, 2)


def get_valuation(symbol: str, market: str = CN_MARKET) -> PointSet:
    """取最新估值及其历史分位。

    Raises:
        MarketNotSupported / SymbolNotFound / UpstreamUnavailable / DataIncomplete
    """
    if market != CN_MARKET:
        raise MarketNotSupported(market, "valuation")
    code = normalize_cn_code(symbol)

    df = fetch_df(SOURCE_VALUE_EM, ak.stock_value_em, symbol=code)

    if "数据日期" not in df.columns:
        raise DataIncomplete(SOURCE_VALUE_EM, ["数据日期"])

    df = df.sort_values("数据日期")
    latest = df.iloc[-1]
    as_of = _as_date(latest["数据日期"])

    points: dict[str, DataPoint] = {}
    for column, (key, unit) in _COLUMN_MAP.items():
        if column not in df.columns:
            continue
        raw = latest[column]
        if pd.isna(raw):
            continue
        points[key] = DataPoint(
            key=key, value=float(raw), as_of=as_of, source=SOURCE_VALUE_EM, unit=unit
        )

    if not points:
        raise DataIncomplete(SOURCE_VALUE_EM, sorted(_COLUMN_MAP))

    window = df.tail(_PERCENTILE_WINDOW)
    for column, key in (("PE(TTM)", "valuation_pe_percentile"), ("市净率", "valuation_pb_percentile")):
        base_key = "valuation_pe" if column == "PE(TTM)" else "valuation_pb"
        if column not in df.columns or base_key not in points:
            continue
        pct = _percentile(window[column], points[base_key].value)
        if pct is None:
            continue
        points[key] = DataPoint(
            key=key,
            value=pct,
            as_of=as_of,
            source=SOURCE_VALUE_EM,
            unit="%",
            period=f"{_as_date(window.iloc[0]['数据日期'])}~{as_of}",
            warnings=(f"分位基于 {len(window)} 个交易日样本",),
        )

    return PointSet(symbol=code, points=points)


def get_valuation_series_baidu(
    symbol: str, indicator: str = "市盈率(TTM)", period: str = "近一年", market: str = CN_MARKET
) -> pd.DataFrame:
    """百度估值序列，作为东财不可用时的 fallback（返回 date/value 两列）。"""
    if market != CN_MARKET:
        raise MarketNotSupported(market, "valuation")
    code = normalize_cn_code(symbol)
    return fetch_df(
        SOURCE_BAIDU, ak.stock_zh_valuation_baidu, symbol=code, indicator=indicator, period=period
    )

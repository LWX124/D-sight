"""财务：按报告期的收入、利润、ROE、负债率、经营现金流等。

源：新浪 `stock_financial_abstract`。返回形如
`选项 | 指标 | 20260331 | 20251231 | ...`，列即报告期。

A 股季报为年初至今累计口径，因此同比只与**去年同期**比较（20260331 vs 20250331），
不与上一列（20251231）比较——后者是常见的口径错误。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import akshare as ak
import pandas as pd

from .akshare_client import fetch_df
from .errors import DataIncomplete, MarketNotSupported
from .schemas import DataPoint, PointSet
from .symbols import CN_MARKET, normalize_cn_code

SOURCE_ABSTRACT = "akshare:stock_financial_abstract(sina)"

# 指标名 → (内部 key, 单位)。同名指标在多个"选项"分组下重复出现，取首个即可。
_METRIC_MAP: dict[str, tuple[str, Optional[str]]] = {
    "营业总收入": ("fundamentals_revenue", "CNY"),
    "归母净利润": ("fundamentals_net_income", "CNY"),
    "营业成本": ("fundamentals_cost_of_revenue", "CNY"),
    "股东权益合计(净资产)": ("fundamentals_shareholders_equity", "CNY"),
    "经营现金流量净额": ("fundamentals_operating_cash_flow", "CNY"),
    "基本每股收益": ("fundamentals_eps", "CNY/share"),
    "净资产收益率(ROE)": ("fundamentals_roe", "%"),
    "资产负债率": ("fundamentals_debt_ratio", "%"),
    "毛利率": ("fundamentals_gross_margin", "%"),
    "销售净利率": ("fundamentals_net_margin", "%"),
    "流动比率": ("fundamentals_current_ratio", "x"),
    "商誉": ("fundamentals_goodwill", "CNY"),
}

# 需要同比的项：写入 _current / _previous 供 indicators 计算增长率
_YOY_KEYS = ("fundamentals_revenue", "fundamentals_net_income")


def _period_to_date(period: str) -> date:
    return date(int(period[:4]), int(period[4:6]), int(period[6:8]))


def _same_period_last_year(period: str) -> str:
    return f"{int(period[:4]) - 1}{period[4:]}"


def get_financials(symbol: str, market: str = CN_MARKET) -> PointSet:
    """取最新报告期财务指标（含去年同期，用于同比）。

    Raises:
        MarketNotSupported / SymbolNotFound / UpstreamUnavailable / DataIncomplete
    """
    if market != CN_MARKET:
        raise MarketNotSupported(market, "fundamentals")
    code = normalize_cn_code(symbol)

    df = fetch_df(SOURCE_ABSTRACT, ak.stock_financial_abstract, symbol=code)
    if "指标" not in df.columns:
        raise DataIncomplete(SOURCE_ABSTRACT, ["指标"])

    periods = [c for c in df.columns if c.isdigit() and len(c) == 8]
    if not periods:
        raise DataIncomplete(SOURCE_ABSTRACT, ["报告期列"])
    periods.sort(reverse=True)
    latest = periods[0]
    as_of = _period_to_date(latest)
    prev_year = _same_period_last_year(latest)

    # 指标名 → 该行（重复指标取首行）
    rows: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        name = str(row["指标"]).strip()
        rows.setdefault(name, row)

    points: dict[str, DataPoint] = {}
    for metric, (key, unit) in _METRIC_MAP.items():
        row = rows.get(metric)
        if row is None or latest not in row or pd.isna(row[latest]):
            continue
        points[key] = DataPoint(
            key=key,
            value=float(row[latest]),
            as_of=as_of,
            source=SOURCE_ABSTRACT,
            unit=unit,
            period=latest,
        )

        if key in _YOY_KEYS:
            points[f"{key}_current"] = DataPoint(
                key=f"{key}_current", value=float(row[latest]), as_of=as_of,
                source=SOURCE_ABSTRACT, unit=unit, period=latest,
            )
            if prev_year in row and pd.notna(row[prev_year]):
                points[f"{key}_previous"] = DataPoint(
                    key=f"{key}_previous", value=float(row[prev_year]),
                    as_of=_period_to_date(prev_year), source=SOURCE_ABSTRACT,
                    unit=unit, period=prev_year,
                )

    if not points:
        raise DataIncomplete(SOURCE_ABSTRACT, sorted(_METRIC_MAP))

    # 毛利 = 营业总收入 − 营业成本：对已披露值的恒等变换，非估算，标注来源
    revenue = points.get("fundamentals_revenue")
    cost = points.get("fundamentals_cost_of_revenue")
    if revenue and cost:
        points["fundamentals_gross_profit"] = DataPoint(
            key="fundamentals_gross_profit",
            value=float(revenue.value) - float(cost.value),
            as_of=as_of,
            source=SOURCE_ABSTRACT,
            unit="CNY",
            period=latest,
            warnings=("由 营业总收入−营业成本 计算",),
        )

    return PointSet(symbol=code, points=points)


def available_periods(symbol: str, market: str = CN_MARKET) -> list[str]:
    """列出可用报告期（降序），用于排查数据新鲜度。"""
    if market != CN_MARKET:
        raise MarketNotSupported(market, "fundamentals")
    df = fetch_df(SOURCE_ABSTRACT, ak.stock_financial_abstract, symbol=normalize_cn_code(symbol))
    return sorted([c for c in df.columns if c.isdigit() and len(c) == 8], reverse=True)

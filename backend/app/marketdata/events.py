"""公司事件：分红、送转、最近一次业绩披露。

源：东财 `stock_fhps_detail_em`（datacenter-web 域，未被出口代理拦截）。
一次调用返回该股历年分红送转明细，含报告期、业绩披露日期、现金分红比例、
送转比例、股权登记日、除权除息日、方案进度。

取**最新报告期**那一行。方案可能仍是"董事会预案"而非"实施分配"——
这会直接影响能否吃到这次分红，因此进度状态必须随值一起暴露，不能只给金额。
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

SOURCE_FHPS = "akshare:stock_fhps_detail_em"

_PERIOD_COL = "报告期"
_DISCLOSE_COL = "业绩披露日期"
_PROGRESS_COL = "方案进度"
_IMPLEMENTED = "实施分配"


def _as_date(value) -> Optional[date]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _number(row: pd.Series, column: str) -> Optional[float]:
    if column not in row.index:
        return None
    value = row[column]
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(row: pd.Series, column: str) -> Optional[str]:
    if column not in row.index:
        return None
    value = row[column]
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def get_events(symbol: str, market: str = CN_MARKET) -> PointSet:
    """取最新报告期的分红送转方案与业绩披露日期。

    Raises:
        MarketNotSupported / SymbolNotFound / UpstreamUnavailable / DataIncomplete
    """
    if market != CN_MARKET:
        raise MarketNotSupported(market, "events")
    code = normalize_cn_code(symbol)

    df = fetch_df(SOURCE_FHPS, ak.stock_fhps_detail_em, symbol=code)
    if _PERIOD_COL not in df.columns:
        raise DataIncomplete(SOURCE_FHPS, [_PERIOD_COL])

    df = df.copy()
    df["_period"] = df[_PERIOD_COL].map(_as_date)
    df = df.dropna(subset=["_period"]).sort_values("_period")
    if df.empty:
        raise DataIncomplete(SOURCE_FHPS, ["有效报告期"])

    latest = df.iloc[-1]

    # 最新一行常常只是「预披露／董事会预案」，没有确切金额（实测 600519 即如此）。
    # 因此分两路取：最新方案反映"接下来要发生什么"，最近一次有确切金额的方案
    # 反映"上一次实际分了多少"。两者报告期不同，各自带自己的 period/as_of。
    concrete = None
    with_amount = df[df["现金分红-现金分红比例"].notna()] if "现金分红-现金分红比例" in df else df.iloc[0:0]
    if not with_amount.empty:
        concrete = with_amount.iloc[-1]

    def make(row: pd.Series):
        period_date: date = row["_period"]
        # as_of 是"什么时候被公告的"，不是报告期——预披露的公告日可以早于报告期末。
        as_of = (
            _as_date(row.get("最新公告日期"))
            or _as_date(row.get(_DISCLOSE_COL))
            or period_date
        )
        progress = _text(row, _PROGRESS_COL)
        warnings: tuple[str, ...] = ()
        if progress and progress != _IMPLEMENTED:
            warnings = (f"该方案进度为「{progress}」，尚未实施，金额与除权日可能变动",)

        def point(key: str, value, unit: Optional[str] = None) -> Optional[DataPoint]:
            if value is None:
                return None
            return DataPoint(
                key=key,
                value=value,
                as_of=as_of,
                source=SOURCE_FHPS,
                unit=unit,
                period=period_date.strftime("%Y%m%d"),
                warnings=warnings,
            )

        return point, progress

    point, progress = make(latest)
    candidates = [
        point("events_dividends", _text(latest, "现金分红-现金分红比例描述")),
        point("events_plan_progress", progress),
    ]
    disclose_date = _as_date(latest.get(_DISCLOSE_COL))
    if disclose_date is not None:
        # 最近一次定期报告的实际披露日，用于判断"财报刚出"还是"数据已陈旧"
        candidates.append(point("events_earnings", disclose_date.isoformat()))

    if concrete is not None:
        point, _ = make(concrete)
        candidates += [
            point("events_dividend_per_10_shares", _number(concrete, "现金分红-现金分红比例"), "CNY/10股"),
            point("events_dividend_yield", _number(concrete, "现金分红-股息率"), "ratio"),
            point("events_splits", _number(concrete, "送转股份-送转总比例"), "股/10股"),
        ]
        ex_date = _as_date(concrete.get("除权除息日"))
        if ex_date is not None:
            candidates.append(point("events_ex_dividend_date", ex_date.isoformat()))

    points = {p.key: p for p in candidates if p is not None}
    if not points:
        raise DataIncomplete(SOURCE_FHPS, ["分红/送转/披露日"])

    return PointSet(symbol=code, points=points)

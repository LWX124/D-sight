"""行情：日线（前复权）与最新价。

源：新浪 `stock_zh_a_daily`（adjust=qfq）。东财 `stock_zh_a_hist` 亦可用，
作为 fallback——两者字段名不同，在此统一成 Bar。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import akshare as ak
import pandas as pd

from .akshare_client import fetch_df
from .errors import DataIncomplete, MarketNotSupported
from .schemas import Bar, DailyBars, DataPoint
from .symbols import CN_MARKET, normalize_cn_code, to_sina_symbol

SOURCE_SINA_DAILY = "akshare:stock_zh_a_daily(sina,qfq)"
SOURCE_EM_HIST = "akshare:stock_zh_a_hist(em,qfq)"


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _require_market(market: str, capability: str) -> None:
    if market != CN_MARKET:
        raise MarketNotSupported(market, capability)


def _bars_from_sina(df: pd.DataFrame) -> list[Bar]:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise DataIncomplete(SOURCE_SINA_DAILY, missing)
    return [
        Bar(
            date=_as_date(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            amount=float(row["amount"]) if "amount" in df.columns and pd.notna(row["amount"]) else None,
            turnover=float(row["turnover"]) if "turnover" in df.columns and pd.notna(row["turnover"]) else None,
        )
        for _, row in df.iterrows()
    ]


def _bars_from_em(df: pd.DataFrame) -> list[Bar]:
    required = {"日期", "开盘", "最高", "最低", "收盘", "成交量"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise DataIncomplete(SOURCE_EM_HIST, missing)
    return [
        Bar(
            date=_as_date(row["日期"]),
            open=float(row["开盘"]),
            high=float(row["最高"]),
            low=float(row["最低"]),
            close=float(row["收盘"]),
            volume=float(row["成交量"]),
            amount=float(row["成交额"]) if "成交额" in df.columns and pd.notna(row["成交额"]) else None,
            turnover=float(row["换手率"]) if "换手率" in df.columns and pd.notna(row["换手率"]) else None,
        )
        for _, row in df.iterrows()
    ]


def get_daily_bars(symbol: str, market: str = CN_MARKET, lookback: int = 300) -> DailyBars:
    """取最近 `lookback` 根前复权日线。

    Raises:
        MarketNotSupported / SymbolNotFound / UpstreamUnavailable / DataIncomplete
    """
    _require_market(market, "daily_bars")
    code = normalize_cn_code(symbol)

    df = fetch_df(
        SOURCE_SINA_DAILY,
        ak.stock_zh_a_daily,
        symbol=to_sina_symbol(code),
        adjust="qfq",
    )
    bars = _bars_from_sina(df)
    bars.sort(key=lambda b: b.date)
    if lookback > 0:
        bars = bars[-lookback:]
    return DailyBars(symbol=code, bars=bars, source=SOURCE_SINA_DAILY)


def get_daily_bars_em(symbol: str, market: str = CN_MARKET, lookback: int = 300) -> DailyBars:
    """东财日线，作为新浪源不可用时的 fallback。"""
    _require_market(market, "daily_bars")
    code = normalize_cn_code(symbol)

    df = fetch_df(
        SOURCE_EM_HIST,
        ak.stock_zh_a_hist,
        symbol=code,
        period="daily",
        adjust="qfq",
    )
    bars = _bars_from_em(df)
    bars.sort(key=lambda b: b.date)
    if lookback > 0:
        bars = bars[-lookback:]
    return DailyBars(symbol=code, bars=bars, source=SOURCE_EM_HIST)


def latest_quote(bars: DailyBars) -> dict[str, DataPoint]:
    """由日线末根导出收盘价与成交量。

    注意：这是**日线收盘价**，盘中不等于实时价——`as_of` 即为该交易日日期，
    上层据此判断是否 stale，本层不做任何插值。
    """
    if not bars.bars:
        raise DataIncomplete(bars.source, ["bars"])
    last = bars.bars[-1]
    return {
        "quote_price": DataPoint(
            key="quote_price",
            value=last.close,
            as_of=last.date,
            source=bars.source,
            unit="CNY",
            warnings=("日线收盘价，非实时报价",),
        ),
        "quote_volume": DataPoint(
            key="quote_volume",
            value=last.volume,
            as_of=last.date,
            source=bars.source,
            unit="shares",
        ),
    }


def get_quote(symbol: str, market: str = CN_MARKET) -> dict[str, DataPoint]:
    """便捷入口：取最近日线并导出收盘价/成交量。"""
    bars = get_daily_bars(symbol, market=market, lookback=5)
    return latest_quote(bars)


def prev_close(bars: DailyBars) -> Optional[float]:
    return bars.bars[-2].close if len(bars.bars) >= 2 else None

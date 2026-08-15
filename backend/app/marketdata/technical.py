"""技术指标：纯函数，输入日线序列，输出带溯源的取值。

不访问网络。样本不足时**不产出该项**（而非用短窗口凑一个数），
缺口由上层映射为 missing。
"""

from __future__ import annotations

import math
from statistics import pstdev
from typing import Optional

from .schemas import DailyBars, DataPoint, PointSet

TRADING_DAYS_PER_YEAR = 244
SOURCE_SUFFIX = "+local_calc"


def sma(values: list[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema_series(values: list[float], window: int) -> list[float]:
    """指数移动平均序列，首值用前 window 根的简单均值播种。"""
    if len(values) < window:
        return []
    k = 2 / (window + 1)
    seed = sum(values[:window]) / window
    out = [seed]
    for value in values[window:]:
        out.append(value * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], window: int = 14) -> Optional[float]:
    """Wilder RSI。"""
    if len(values) < window + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(values[-(window + 1):-1], values[-window:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd(values: list[float], fast: int = 12, slow: int = 26) -> Optional[float]:
    """MACD 快线（DIF = EMA12 − EMA26）。"""
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    if not fast_series or not slow_series:
        return None
    # 两条 EMA 起点不同，按尾部对齐
    return fast_series[-1] - slow_series[-1]


def bollinger(values: list[float], window: int = 20, num_std: float = 2.0):
    if len(values) < window:
        return None, None
    mid = sum(values[-window:]) / window
    sd = pstdev(values[-window:])
    return mid + num_std * sd, mid - num_std * sd


def volatility(values: list[float], window: int) -> Optional[float]:
    """年化波动率（%），基于对数收益。"""
    if len(values) < window + 1:
        return None
    returns = [
        math.log(cur / prev)
        for prev, cur in zip(values[-(window + 1):-1], values[-window:])
        if prev > 0 and cur > 0
    ]
    if len(returns) < window:
        return None
    return pstdev(returns) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100


def max_drawdown(values: list[float], window: int) -> Optional[float]:
    """窗口内最大回撤（%，负值）。"""
    if len(values) < window:
        return None
    sample = values[-window:]
    peak = sample[0]
    worst = 0.0
    for value in sample:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return worst * 100


def atr(bars: DailyBars, window: int = 14) -> Optional[float]:
    """平均真实波幅。"""
    if len(bars) < window + 1:
        return None
    trs = []
    for prev, cur in zip(bars.bars[-(window + 1):-1], bars.bars[-window:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / window


def volume_trend(volumes: list[float], short: int = 5, long: int = 20) -> Optional[float]:
    """近 5 日均量 / 近 20 日均量，>1 为放量。"""
    if len(volumes) < long:
        return None
    long_avg = sum(volumes[-long:]) / long
    if long_avg <= 0:
        return None
    return (sum(volumes[-short:]) / short) / long_avg


def compute_technicals(bars: DailyBars) -> PointSet:
    """由日线计算全部技术/风险指标。"""
    closes = bars.closes
    as_of = bars.as_of
    source = bars.source + SOURCE_SUFFIX

    boll_upper, boll_lower = bollinger(closes)
    raw: dict[str, tuple[Optional[float], Optional[str], Optional[str]]] = {
        "technical_sma_20": (sma(closes, 20), "price", "20d"),
        "technical_sma_50": (sma(closes, 50), "price", "50d"),
        "technical_sma_200": (sma(closes, 200), "price", "200d"),
        "technical_rsi_14": (rsi(closes, 14), None, "14d"),
        "technical_macd": (macd(closes), "price", "12/26"),
        "technical_bollinger_upper": (boll_upper, "price", "20d,2sd"),
        "technical_bollinger_lower": (boll_lower, "price", "20d,2sd"),
        "technical_volume_trend": (volume_trend(bars.volumes), "ratio", "5d/20d"),
        "technical_volatility_20d": (volatility(closes, 20), "%", "20d"),
        "risk_volatility_20d": (volatility(closes, 20), "%", "20d"),
        "risk_volatility_60d": (volatility(closes, 60), "%", "60d"),
        "risk_max_drawdown_60d": (max_drawdown(closes, 60), "%", "60d"),
        "risk_atr_14": (atr(bars, 14), "price", "14d"),
    }

    points = {
        key: DataPoint(
            key=key, value=round(value, 4), as_of=as_of, source=source, unit=unit, period=period
        )
        for key, (value, unit, period) in raw.items()
        if value is not None
    }
    return PointSet(symbol=bars.symbol, points=points)

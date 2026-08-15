"""akshare 调用统一入口：限频、重试、异常归一。

akshare 无 SLA，且本环境已确认东财 `push2.*` 实时推送域被出口代理拦截
（`datacenter-web` / `quote` 域正常）——所有接口选型见
`.trellis/tasks/08-14-phase0-foundation/research/akshare-probe.md`。
本层只负责"把 DataFrame 拿回来或抛类型化异常"，不做任何字段语义解释。
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any, Callable, Optional

import pandas as pd

from app.core.akshare_runtime import call_akshare

from .errors import SymbolNotFound, UpstreamUnavailable

logger = logging.getLogger(__name__)

# 进程内最小调用间隔，避免被上游限频。akshare 调用本就被 call_akshare 串行化，
# 这里只需在同一把锁下补一个节流。
_MIN_INTERVAL_SEC = 0.2
_RETRY_BACKOFF_SEC = 1.0

_throttle_lock = Lock()
_last_call_at: float = 0.0

# 同一次诊断里 quote / daily_bars / technical 三个证据块要用同一份日线，
# 60s 备忘避免重复打上游。日线与财务的更新粒度都远大于 60s，不影响 as_of 语义。
_CACHE_TTL_SEC = 60.0
_cache_lock = Lock()
_df_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}

# akshare 解析上游返回体失败时抛的异常族；出现即说明"接口通、但这个代码没数据"。
_PAYLOAD_ERRORS = (KeyError, IndexError)


def _throttle() -> None:
    global _last_call_at
    with _throttle_lock:
        elapsed = time.monotonic() - _last_call_at
        if elapsed < _MIN_INTERVAL_SEC:
            time.sleep(_MIN_INTERVAL_SEC - elapsed)
        _last_call_at = time.monotonic()


def _cache_get(key: tuple) -> Optional[pd.DataFrame]:
    with _cache_lock:
        hit = _df_cache.get(key)
        if hit is None:
            return None
        cached_at, df = hit
        if time.monotonic() - cached_at > _CACHE_TTL_SEC:
            _df_cache.pop(key, None)
            return None
        return df


def _cache_put(key: tuple, df: pd.DataFrame) -> None:
    with _cache_lock:
        _df_cache[key] = (time.monotonic(), df)


def clear_cache() -> None:
    """清空取数备忘。测试与"强制刷新"场景使用。"""
    with _cache_lock:
        _df_cache.clear()


def fetch_df(
    endpoint: str,
    func: Callable[..., Any],
    *,
    retries: int = 1,
    **kwargs: Any,
) -> pd.DataFrame:
    """调用一个返回 DataFrame 的 akshare 接口。

    `kwargs` 原样转发给 akshare——本函数不得声明与 akshare 参数同名的形参
    （曾因声明 `symbol` 把标的吞掉，导致 akshare 用默认股票返回数据）。

    Args:
        endpoint: 用于日志与异常信息的接口标识，同时作为 DataPoint.source 前缀。
        func: akshare 函数对象。
        retries: 失败后的额外重试次数。

    Raises:
        UpstreamUnavailable: 网络/代理/超时/接口变更。
        SymbolNotFound: 上游可达但返回空。
    """
    cache_key = (endpoint, tuple(sorted(kwargs.items())))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    last_exc: Optional[BaseException] = None

    for attempt in range(retries + 1):
        _throttle()
        try:
            df = call_akshare(func, **kwargs)
        except _PAYLOAD_ERRORS as exc:
            # 上游可达但返回体不含预期字段——A 股接口对未知代码就是这个表现，
            # 重试无意义。
            raise SymbolNotFound(str(kwargs.get("symbol", "?")), endpoint) from exc
        except Exception as exc:  # akshare 内部异常类型不稳定，统一归一
            last_exc = exc
            logger.warning(
                "akshare %s 调用失败 (attempt %s/%s): %s",
                endpoint, attempt + 1, retries + 1, exc,
            )
            if attempt < retries:
                time.sleep(_RETRY_BACKOFF_SEC * (attempt + 1))
            continue

        if df is None or not isinstance(df, pd.DataFrame):
            raise UpstreamUnavailable(endpoint, TypeError(f"返回类型 {type(df).__name__}"))
        if df.empty:
            raise SymbolNotFound(str(kwargs.get("symbol", "?")), endpoint)
        _cache_put(cache_key, df)
        return df

    raise UpstreamUnavailable(endpoint, last_exc)

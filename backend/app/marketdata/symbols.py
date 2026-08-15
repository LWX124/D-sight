"""A 股代码归一。

只处理 6 位数字代码；带前缀/后缀（sh600519、600519.SH）先剥离再判交易所。
北交所判定必须早于沪市：920xxx/4xxxxx/8xxxxx 属北交所，而 900xxx 是沪市 B 股。
"""

from __future__ import annotations

import re

from .errors import SymbolNotFound

_CODE_RE = re.compile(r"(\d{6})")

CN_MARKET = "CN"


def normalize_cn_code(symbol: str) -> str:
    """提取 6 位 A 股代码。"""
    match = _CODE_RE.search(symbol or "")
    if not match:
        raise SymbolNotFound(symbol, "symbol_normalizer")
    return match.group(1)


def exchange_of(code: str) -> str:
    """返回 sh / sz / bj。"""
    if code.startswith(("92", "4", "8")):
        return "bj"
    if code.startswith(("6", "9")):
        return "sh"
    return "sz"


def to_sina_symbol(symbol: str) -> str:
    """600519 → sh600519（新浪源接口所需格式）。"""
    code = normalize_cn_code(symbol)
    return f"{exchange_of(code)}{code}"


def to_xq_symbol(symbol: str) -> str:
    """600519 → SH600519（雪球/部分接口所需格式）。"""
    code = normalize_cn_code(symbol)
    return f"{exchange_of(code).upper()}{code}"

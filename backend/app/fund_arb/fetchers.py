"""公开数据源抓取。单符号/单基金失败隔离；新浪一次 HTTP 批量取全部符号。

字段下标以真实抓包样本为准（2026-07-20），修改下标必须同步改测试 fixture。
"""
import asyncio
import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

_log = logging.getLogger(__name__)

SPOT_FX_SINA = {"USD": "fx_susdcnh", "HKD": "fx_shkdcny", "JPY": "fx_sjpycny"}
MID_FX_SYMBOL = {"USD": "USDCNH_MID", "HKD": "HKDCNY_MID", "JPY": "JPYCNY_MID"}

_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}
_EM_HEADERS = {"Referer": "http://fundf10.eastmoney.com/"}


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float | None = None
    pct: float | None = None
    prev_settle: float | None = None


@dataclass
class NavRecord:
    date: dt.date
    nav: float | None
    acc_nav: float | None
    dividend: str | None


class QuoteFetcher(ABC):
    @abstractmethod
    async def fetch_quotes(self, symbols: list[str]) -> dict[str, Quote]: ...


class FakeQuoteFetcher(QuoteFetcher):
    def __init__(self, quotes: dict[str, Quote]):
        self.quotes = quotes

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        return {s: self.quotes[s] for s in symbols if s in self.quotes}


def _parse_sina_line(symbol: str, fields: list[str]) -> Quote | None:
    """根据符号前缀解析新浪行情行。字段下标以 2026-07-20 真实抓包为准。"""
    if symbol.startswith(("sh", "sz")):
        # A股/基金/指数：[2]昨收 [3]现价
        price, prev = float(fields[3]), float(fields[2])
        pct = (price / prev - 1) * 100 if prev > 0 else None
        return Quote(symbol=symbol, price=price, prev_close=prev, pct=pct)
    if symbol.startswith("gb_"):
        # 美股：[1]现价 [2]涨跌幅%
        price, pct = float(fields[1]), float(fields[2])
        prev = price / (1 + pct / 100) if pct > -100 else None
        return Quote(symbol=symbol, price=price, prev_close=prev, pct=pct)
    if symbol.startswith("hf_"):
        # 国际期货（hf_CL原油/hf_NQ纳指等）：[0]现价 [7]昨结算
        return Quote(symbol=symbol, price=float(fields[0]), prev_settle=float(fields[7]))
    if symbol.startswith("nf_"):
        # 国内期货：[8]最新价 [10]昨结算
        return Quote(symbol=symbol, price=float(fields[8]), prev_settle=float(fields[10]))
    if symbol.startswith("int_"):
        # 国际指数（int_nikkei 等）：[1]现价 [3]涨跌幅%
        return Quote(symbol=symbol, price=float(fields[1]), pct=float(fields[3]))
    if symbol.startswith("rt_"):
        # 港股指数（rt_hkHSI 等）：[6]现价 [3]昨收 [8]涨跌幅%
        price, prev = float(fields[6]), float(fields[3])
        return Quote(symbol=symbol, price=price, prev_close=prev, pct=float(fields[8]))
    if symbol.startswith("fx_"):
        # 外汇：[1]买价
        return Quote(symbol=symbol, price=float(fields[1]))
    return None


class SinaQuoteFetcher(QuoteFetcher):
    async def fetch_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        import subprocess
        url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
        cmd = ["curl", "-s", url, "-H", "Referer: https://finance.sina.com.cn"]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            text = result.stdout.decode('gbk', errors='ignore')
        except Exception as e:
            _log.error("curl failed: %s", e)
            return {}

        out: dict[str, Quote] = {}
        for line in text.splitlines():
            if "=" not in line or "hq_str_" not in line:
                continue
            name = line.split("hq_str_", 1)[1].split("=", 1)[0]
            payload = line.split('"')[1] if '"' in line else ""
            fields = payload.split(",")
            try:
                q = _parse_sina_line(name, fields)
            except (ValueError, IndexError):
                q = None
            if q is not None and q.price > 0:
                out[name] = q
            elif name in symbols:
                _log.warning("sina 行情坏行已隔离：%s", name)
        return out


async def fetch_nav_history(fund_code: str, count: int = 60) -> list[NavRecord]:
    """东财历史净值（新→旧）。"""
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    params = {"fundCode": fund_code, "pageIndex": 1, "pageSize": count}
    async with httpx.AsyncClient(timeout=30, headers=_EM_HEADERS) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    out = []
    for it in data.get("Data", {}).get("LSJZList", []):
        try:
            out.append(NavRecord(
                date=dt.date.fromisoformat(it["FSRQ"]),
                nav=float(it["DWJZ"]) if it.get("DWJZ") else None,
                acc_nav=float(it["LJJZ"]) if it.get("LJJZ") else None,
                dividend=it.get("FHSP") or None,
            ))
        except (ValueError, KeyError):
            continue
    return out


async def fetch_fx_mid() -> dict[str, float]:
    """外管局/chinamoney 人民币中间价。JPY 按 100JPY 报价换算为 1JPY。"""
    url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url)
        r.raise_for_status()
        data = r.json()
    out: dict[str, float] = {}
    for rec in data.get("records", []):
        name, price = rec.get("vrtName", ""), rec.get("price")
        if not price:
            continue
        if name == "USD/CNY":
            out["USDCNY_MID"] = float(price)
        elif name == "HKD/CNY":
            out["HKDCNY_MID"] = float(price)
        elif name == "100JPY/CNY":
            out["JPYCNY_MID"] = float(price) / 100.0
    return out


async def fetch_purchase_status() -> dict[str, dict]:
    """akshare 东财申赎状态（同步 → to_thread）。"""
    import akshare as ak

    df = await asyncio.to_thread(ak.fund_purchase_em)
    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        raw_limit = row.get("日累计限定金额", "")
        limit_str = str(raw_limit) if raw_limit is not None and str(raw_limit) not in ("", "nan", "无限制") else None
        out[str(row["基金代码"])] = {
            "purchase_status": str(row.get("申购状态", "")),
            "redemption_status": str(row.get("赎回状态", "")),
            "purchase_limit": limit_str,
        }
    return out

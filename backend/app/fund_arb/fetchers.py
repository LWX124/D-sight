"""公开数据源抓取。单符号/单基金失败隔离；新浪一次 HTTP 批量取全部符号。

字段下标以真实抓包样本为准（2026-07-20），修改下标必须同步改测试 fixture。
"""
import asyncio
import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.akshare_runtime import call_akshare

_log = logging.getLogger(__name__)

SPOT_FX_SINA = {"USD": "fx_susdcny", "HKD": "fx_shkdcny", "JPY": "fx_sjpycny"}
MID_FX_SYMBOL = {"USD": "USDCNY_MID", "HKD": "HKDCNY_MID", "JPY": "JPYCNY_MID"}

# Sina hq.sinajs.cn 不支持的代码：实测返回空 payload 或全 0，每个 tick 都打 warning
# 且浪费一次 HTTP 请求。这些代码的实时价格已由东财 push2/kline 兜底（见
# _EM_PUSH2_CODES / _EM_KLINE_CODES / fetch_realtime_prices）。
# 1) 中证指数代码（sh9xxxxx / sh000xxx 申赎地）：新浪不支持，直接跳过。
#    东财 secid 前缀规则：930xxx/950xxx 用 2.（个股/指数混编），000xxx 用 1.（上证指数）。
# 2) 部分 LOF 场内价新浪返回 0：由腾讯 qt.gtimg.cn 兜底。
SINA_UNSUPPORTED_INDEXES = frozenset({
    "sh930094", "sh930713", "sh930720", "sh930875", "sh930898",
    "sh930914", "sh930917", "sh930997", "sh950090",
    "sh000922", "sh000961", "sh000979",
})
# 东财 secid 前缀：sh000xxx 用 1.（上证指数），其余 sh9xxxxx 用 2.
EM_INDEX_PREFIX1 = frozenset({"sh000922", "sh000961", "sh000979"})
SINA_UNSUPPORTED_LOFS = frozenset({
    "sz161604", "sz165523",  # 新浪返回空；腾讯兜底
})

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


@dataclass
class DatedPrice:
    """带源日期的价格记录，用于 LBMA 等以发布日为准的定盘价序列。"""
    date: dt.date
    price: float


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
    async def _fetch_raw(self, symbols: list[str]) -> str:
        """拉取新浪行情原始文本。抽成方法便于测试注入。"""
        import subprocess
        url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
        cmd = ["curl", "-s", url, "-H", "Referer: https://finance.sina.com.cn"]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            return result.stdout.decode('gbk', errors='ignore')
        except Exception as e:
            _log.error("curl failed: %s", e)
            return ""

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        text = await self._fetch_raw(symbols)
        if not text:
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


LBMA_GOLD_PM = "LBMA_GOLD_PM"


async def fetch_lbma_gold_pm(limit: int | None = 1) -> list[DatedPrice]:
    """LBMA 黄金 PM 定盘价（USD/oz），保留每条记录的实际定盘日期。

    limit=None 返回全量历史，limit=N 返回最近 N 个交易日（默认最新一条）。
    日期取响应中的 ``d`` 字段（伦敦定盘日），不能按上海当天落库——上海早盘
    抓到的最新 PM 定盘价通常属于前一个伦敦交易日。
    """
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://prices.lbma.org.uk/json/gold_pm.json",
                        headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    data = r.json()
    out: list[DatedPrice] = []
    for rec in data:
        vs = rec.get("v")
        if not vs or not vs[0]:
            continue
        try:
            out.append(DatedPrice(date=dt.date.fromisoformat(rec["d"]), price=float(vs[0])))
        except (KeyError, ValueError, TypeError):
            continue
    if limit is not None:
        out = out[-limit:]
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


_EM_PUSH2_HEADERS = {"Referer": "https://quote.eastmoney.com/"}
_EM_PUSH2_CODES = frozenset({"930875", "930713", "930720", "950090", "930997"})
_EM_KLINE_CODES = frozenset({"930914", "930917"})


async def _fetch_price_tencent(symbol: str) -> float | None:
    url = f"https://qt.gtimg.cn/q={symbol}"
    async with httpx.AsyncClient(timeout=10, headers={"Referer": "https://finance.qq.com"}) as c:
        r = await c.get(url)
        r.raise_for_status()
    if '"' not in r.text:
        return None
    fields = r.text.split('"')[1].split("~")
    try:
        return float(fields[3])
    except (IndexError, ValueError):
        return None


async def _fetch_price_em_push2(code: str, secid_prefix: str = "2") -> float | None:
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {"secid": f"{secid_prefix}.{code}", "fields": "f43"}
    async with httpx.AsyncClient(timeout=10, headers=_EM_PUSH2_HEADERS) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    val = (data.get("data") or {}).get("f43")
    if val is None or val == "-":
        return None
    return float(val) / 100.0


async def _fetch_price_em_kline(code: str, secid_prefix: str = "2") -> float | None:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid": f"{secid_prefix}.{code}", "fields1": "f1", "fields2": "f51,f52,f53", "klt": 101, "fqt": 0, "lmt": 1}
    async with httpx.AsyncClient(timeout=10, headers=_EM_PUSH2_HEADERS) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    klines = (data.get("data") or {}).get("klines", [])
    if not klines:
        return None
    try:
        return float(klines[-1].split(",")[2])
    except (IndexError, ValueError):
        return None


async def fetch_realtime_prices(fund_codes: list[str]) -> dict[str, float]:
    """按基金代码路由抓取实时价格；不支持的代码静默跳过。"""
    async def _one(fc: str) -> tuple[str, float | None]:
        code = fc.removeprefix("sh")
        try:
            if code in _EM_PUSH2_CODES:
                p = await _fetch_price_em_push2(code)
            elif code in _EM_KLINE_CODES:
                p = await _fetch_price_em_kline(code)
            elif fc in SINA_UNSUPPORTED_INDEXES:
                # 中证指数代码新浪不支持。东财 secid 前缀按交易所/类型区分：
                # sh000xxx（上证指数）用 1.，sh9xxxxx（中证）用 2.。
                prefix = "1" if fc in EM_INDEX_PREFIX1 else "2"
                p = (await _fetch_price_em_push2(code, prefix)
                     or await _fetch_price_em_kline(code, prefix))
            elif fc in SINA_UNSUPPORTED_LOFS:
                p = await _fetch_price_tencent(fc)
            else:
                return fc, None
        except Exception:
            _log.warning("实时价格抓取失败：%s", fc)
            return fc, None
        return fc, p

    pairs = await asyncio.gather(*[_one(fc) for fc in fund_codes])
    return {fc: p for fc, p in pairs if p is not None}


async def fetch_purchase_status() -> dict[str, dict]:
    """akshare 东财申赎状态（同步 → to_thread）。"""
    import akshare as ak

    df = await asyncio.to_thread(call_akshare, ak.fund_purchase_em)
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

"""一次性历史回填：基金净值 / 跟踪标的收盘 / 汇率中间价。幂等，单符号失败隔离。"""
import asyncio
import datetime as dt
import logging

import httpx
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.fund_arb.fetchers import MID_FX_SYMBOL, fetch_nav_history
from app.fund_arb.job import _upsert_daily, _upsert_tracking
from app.fund_arb.models import FundArbFund

_log = logging.getLogger(__name__)

STOOQ_MAP = {"int_nikkei": "^nkx", "rt_hkHSI": "^hsi", "rt_hkHSCEI": "^hsce"}


async def _fetch_symbol_history(symbol: str, days: int) -> dict[dt.date, float]:
    import akshare as ak
    import pandas as pd

    if symbol in STOOQ_MAP:
        url = f"https://stooq.com/q/d/l/?s={STOOQ_MAP[symbol]}&i=d"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
        out = {}
        for line in r.text.splitlines()[1:]:
            parts = line.split(",")
            try:
                out[dt.date.fromisoformat(parts[0])] = float(parts[4])
            except (ValueError, IndexError):
                continue
        return out
    if symbol.startswith("gb_"):
        df = await asyncio.to_thread(ak.stock_us_daily, symbol=symbol[3:].upper())
        df = df.tail(days + 10)
        return {pd.Timestamp(row["date"]).date(): float(row["close"])
                for _, row in df.iterrows()}
    if symbol.startswith("nf_"):
        df = await asyncio.to_thread(ak.futures_main_sina, symbol=symbol[3:])
        df = df.tail(days + 10)
        return {pd.Timestamp(row["日期"]).date(): float(row["收盘价"])
                for _, row in df.iterrows()}
    if symbol.startswith(("sh", "sz")):
        df = await asyncio.to_thread(ak.stock_zh_index_daily, symbol=symbol)
        df = df.tail(days + 10)
        return {pd.Timestamp(row["date"]).date(): float(row["close"])
                for _, row in df.iterrows()}
    raise ValueError(f"未知历史源：{symbol}")


async def _fetch_fx_mid_history(days: int) -> dict[str, dict[dt.date, float]]:
    end = dt.date.today()
    start = end - dt.timedelta(days=days + 10)
    url = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew"
    params = {"startDate": start.isoformat(), "endDate": end.isoformat(),
              "currency": "USD/CNY,HKD/CNY,100JPY/CNY"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    out: dict[str, dict[dt.date, float]] = {v: {} for v in MID_FX_SYMBOL.values()}
    for rec in data.get("records", []):
        d = dt.date.fromisoformat(rec["date"])
        vals = rec.get("values")
        if vals and len(vals) >= 3:
            out["USDCNY_MID"][d] = float(vals[0])
            out["HKDCNY_MID"][d] = float(vals[1])
            out["JPYCNY_MID"][d] = float(vals[2]) / 100.0
    return out


async def run_bootstrap(days: int = 60) -> dict[str, int]:
    session_factory = get_sessionmaker()
    stats = {"navs": 0, "tracking": 0, "fx": 0, "failed": 0}
    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()

    for fund in funds:
        for attempt in range(3):
            try:
                recs = await fetch_nav_history(fund.fund_code, count=days)
                async with session_factory() as db:
                    for rec in recs:
                        nav = rec.acc_nav if fund.nav_field == "ljjz" else rec.nav
                        if nav is not None:
                            await _upsert_daily(db, fund.fund_code, rec.date, nav=nav)
                            stats["navs"] += 1
                    await db.commit()
                await asyncio.sleep(0.1)  # 避免并发过高
                break
            except Exception as e:
                if attempt == 2:
                    stats["failed"] += 1
                    _log.exception("bootstrap 净值失败：%s", fund.fund_code)
                else:
                    _log.warning("bootstrap 净值重试 %d/3：%s - %s", attempt + 1, fund.fund_code, e)
                    await asyncio.sleep(1)

    symbols = sorted({f.tracking_symbol for f in funds if f.tracking_symbol != "-"})
    cutoff = dt.date.today() - dt.timedelta(days=days + 10)
    for sym in symbols:
        for attempt in range(3):
            try:
                hist = await _fetch_symbol_history(sym, days)
                async with session_factory() as db:
                    for d, close in hist.items():
                        if d >= cutoff:
                            await _upsert_tracking(db, sym, d, close)
                            stats["tracking"] += 1
                    await db.commit()
                await asyncio.sleep(0.1)
                break
            except Exception as e:
                if attempt == 2:
                    stats["failed"] += 1
                    _log.exception("bootstrap 标的历史失败：%s", sym)
                else:
                    _log.warning("bootstrap 标的重试 %d/3：%s - %s", attempt + 1, sym, e)
                    await asyncio.sleep(1)

    try:
        fx = await _fetch_fx_mid_history(days)
        async with session_factory() as db:
            for mid_symbol, series in fx.items():
                for d, rate in series.items():
                    await _upsert_tracking(db, mid_symbol, d, rate)
                    stats["fx"] += 1
            await db.commit()
    except Exception:
        stats["failed"] += 1
        _log.exception("bootstrap 中间价历史失败")

    _log.info("fund_arb bootstrap 完成：%s", stats)
    return stats


if __name__ == "__main__":
    print(asyncio.run(run_bootstrap()))

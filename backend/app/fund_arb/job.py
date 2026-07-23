"""盘中快照 tick、盘后流水线、早盘任务。全部单点失败隔离。"""
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.fund_arb.calibration import calibrate_position
from app.fund_arb.fetchers import (
    MID_FX_SYMBOL,
    FakeQuoteFetcher,
    QuoteFetcher,
    SinaQuoteFetcher,
    fetch_fx_mid,
    fetch_nav_history,
    fetch_purchase_status,
    fetch_realtime_prices,
)
from app.fund_arb.models import FundArbDaily, FundArbFactor, FundArbFund, FundArbTrackingDaily
from app.fund_arb.snapshot import get_store, rebuild_snapshots

_log = logging.getLogger(__name__)
_SH = ZoneInfo("Asia/Shanghai")

CALIBRATION_WINDOW = 20


def _now_sh() -> dt.datetime:
    return dt.datetime.now(_SH)


def is_market_open(now: dt.datetime) -> bool:
    from chinese_calendar import is_workday

    d = now.astimezone(_SH)
    if not is_workday(d.date()) or d.weekday() >= 5:
        return False
    t = d.time()
    return dt.time(9, 25) <= t <= dt.time(15, 5)


def get_fetcher() -> QuoteFetcher:
    if get_settings().fund_arb_backend == "sina":
        return SinaQuoteFetcher()
    return FakeQuoteFetcher({})


async def _upsert_daily(db, fund_code: str, date: dt.date, **fields) -> None:
    stmt = pg_insert(FundArbDaily).values(fund_code=fund_code, date=date, **fields)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_fund_arb_daily_date_code",
        set_={k: stmt.excluded[k] for k in fields},
    )
    await db.execute(stmt)


async def _upsert_tracking(db, symbol: str, date: dt.date, close: float) -> None:
    stmt = pg_insert(FundArbTrackingDaily).values(symbol=symbol, date=date, close=close)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_fund_arb_tracking_date_symbol", set_={"close": stmt.excluded.close}
    )
    await db.execute(stmt)


async def snapshot_tick() -> int:
    now = _now_sh()
    if not is_market_open(now):
        return 0
    n = await rebuild_snapshots(get_sessionmaker(), get_fetcher())
    if now.time() >= dt.time(15, 0):
        await _persist_close(now.date())
    return n


async def _persist_close(today: dt.date) -> None:
    rows = get_store().rows()
    async with get_sessionmaker()() as db:
        for s in rows:
            if s.source != "realtime" or s.price is None:
                continue
            await _upsert_daily(
                db, s.fund_code, today,
                price=s.price, price_pct=s.price_pct, amount=s.amount,
                est_nav_close=s.est_nav, premium=s.premium,
            )
        await db.commit()


async def evening_pipeline() -> None:
    """盘后：净值回填 → 误差对账 → 标的收盘记录 → 回归校准 → 申赎状态。"""
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()

    for fund in funds:
        try:
            recs = await fetch_nav_history(fund.fund_code, count=15)
            async with session_factory() as db:
                for rec in recs:
                    nav = rec.acc_nav if fund.nav_field == "ljjz" else rec.nav
                    if nav is None:
                        continue
                    await _upsert_daily(db, fund.fund_code, rec.date, nav=nav)
                await db.commit()
                rows = (await db.execute(
                    select(FundArbDaily).where(
                        FundArbDaily.fund_code == fund.fund_code,
                        FundArbDaily.nav.is_not(None),
                        FundArbDaily.est_nav_close.is_not(None),
                        FundArbDaily.valuation_error.is_(None),
                    )
                )).scalars().all()
                dividend_dates = {r.date for r in recs if r.dividend}
                for row in rows:
                    if row.date in dividend_dates:
                        continue
                    if row.nav <= 0:
                        continue
                    row.valuation_error = (row.est_nav_close / row.nav - 1.0) * 100.0
                await db.commit()
        except Exception:
            _log.exception("fund_arb 净值回填失败：%s", fund.fund_code)

    today = _now_sh().date()
    symbols = sorted({
        f.tracking_symbol for f in funds
        if f.tracking_symbol != "-" and not f.tracking_symbol.startswith("gb_")
    })
    try:
        quotes = await get_fetcher().fetch_quotes(symbols)
        async with session_factory() as db:
            for sym, q in quotes.items():
                await _upsert_tracking(db, sym, today, q.price)
            await db.commit()
    except Exception:
        _log.exception("fund_arb 标的收盘记录失败")

    await _run_calibration(session_factory, funds, today)

    try:
        async with session_factory() as db:
            done = (await db.execute(
                select(FundArbDaily.id).where(
                    FundArbDaily.date == today,
                    FundArbDaily.purchase_status.is_not(None),
                ).limit(1)
            )).first()
        if done is None:
            status = await fetch_purchase_status()
            async with session_factory() as db:
                for fund in funds:
                    st = status.get(fund.fund_code)
                    if st:
                        await _upsert_daily(db, fund.fund_code, today, **st)
                await db.commit()
    except Exception:
        _log.exception("fund_arb 申赎状态同步失败")


async def _run_calibration(session_factory, funds, today: dt.date) -> None:
    for fund in funds:
        if fund.valuation_method != "index":
            continue
        try:
            async with session_factory() as db:
                navs = (await db.execute(
                    select(FundArbDaily).where(
                        FundArbDaily.fund_code == fund.fund_code,
                        FundArbDaily.nav.is_not(None),
                    ).order_by(FundArbDaily.date.desc()).limit(CALIBRATION_WINDOW + 1)
                )).scalars().all()
                tracks = (await db.execute(
                    select(FundArbTrackingDaily).where(
                        FundArbTrackingDaily.symbol == fund.tracking_symbol,
                    ).order_by(FundArbTrackingDaily.date.desc()).limit(60)
                )).scalars().all()
                mids = {}
                if fund.currency:
                    mid_rows = (await db.execute(
                        select(FundArbTrackingDaily).where(
                            FundArbTrackingDaily.symbol == MID_FX_SYMBOL[fund.currency],
                        ).order_by(FundArbTrackingDaily.date.desc()).limit(60)
                    )).scalars().all()
                    mids = {r.date: r.close for r in mid_rows}
            track_by_date = {r.date: r.close for r in tracks}
            navs = sorted(navs, key=lambda r: r.date)
            nav_returns, track_returns = [], []
            for prev, cur in zip(navs, navs[1:], strict=False):
                tp, tc = track_by_date.get(prev.date), track_by_date.get(cur.date)
                if tp is None or tc is None or tp <= 0:
                    continue
                fx_change = 1.0
                if fund.currency:
                    mp, mc = mids.get(prev.date), mids.get(cur.date)
                    if mp is None or mc is None or mp <= 0:
                        continue
                    fx_change = mc / mp
                if prev.nav <= 0:
                    continue
                nav_returns.append(cur.nav / prev.nav - 1.0)
                track_returns.append((tc / tp) * fx_change - 1.0)
            result = calibrate_position(nav_returns, track_returns)
            if result is None:
                continue
            beta, r2 = result
            async with session_factory() as db:
                stmt = pg_insert(FundArbFactor).values(
                    fund_code=fund.fund_code, date=today,
                    position_beta=beta, r_squared=r2, sample_days=len(nav_returns),
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_fund_arb_factor_code_date",
                    set_={"position_beta": stmt.excluded.position_beta,
                          "r_squared": stmt.excluded.r_squared,
                          "sample_days": stmt.excluded.sample_days},
                )
                await db.execute(stmt)
                await db.commit()
        except Exception:
            _log.exception("fund_arb 校准失败：%s", fund.fund_code)


def _parse_ref_page(html: str) -> dict[str, tuple[float, float]]:
    """解析参考网站列表页，返回 {sina_symbol: (官方est_nav, 官方premium)}。"""
    import re
    out: dict[str, tuple[float, float]] = {}
    # 实际 HTML：>SH501300</a></td><td...><font...>0.937</font></td><td...>2026-07-21</td><td...><font...>-0.69%</font>
    for m in re.finditer(
        r'>([SZ][HZ]\d{6})</a></td>'
        r'<td[^>]*><font[^>]*>([\d.]+)</font></td>'
        r'<td[^>]*>\d{4}-\d{2}-\d{2}</td>'
        r'<td[^>]*><font[^>]*>([-\d.]+)%</font>',
        html,
    ):
        sym, est, prem = m.group(1), float(m.group(2)), float(m.group(3))
        out[sym] = (est, prem)
    return out


_REF_PAGES = [
    "https://www.palmmicro.com/woody/res/qdiicn.php",
    "https://www.palmmicro.com/woody/res/chinaindexcn.php",
    "https://www.palmmicro.com/woody/res/chinafuturecn.php",
    "https://www.palmmicro.com/woody/res/qdiimixcn.php",
    "https://www.palmmicro.com/woody/res/qdiihkcn.php",
    "https://www.palmmicro.com/woody/res/qdiieucn.php",
]


async def _calibrate_ref(warn_threshold: float = 0.5) -> None:
    """抓参考网站所有列表页，与数据库最新估值对比，偏差超阈值时告警，同时落库。"""
    import subprocess
    ref_data: dict[str, tuple[float, float]] = {}
    for url in _REF_PAGES:
        try:
            result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=30)
            ref_data.update(_parse_ref_page(result.stdout))
        except Exception:
            _log.exception("fund_arb 参考网站抓取失败：%s", url)
    if not ref_data:
        _log.warning("fund_arb 参考网站解析结果为空")
        return

    today = _now_sh().date()
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()
        fund_map = {f.sina_symbol.upper(): f for f in funds}

        for sym_upper, (ref_est, ref_prem) in ref_data.items():
            fund = fund_map.get(sym_upper)
            if fund is None:
                continue
            row = (await db.execute(
                select(FundArbDaily).where(
                    FundArbDaily.fund_code == fund.fund_code,
                    FundArbDaily.est_nav_close.is_not(None),
                ).order_by(FundArbDaily.date.desc()).limit(1)
            )).scalar_one_or_none()

            if row and row.est_nav_close:
                diff = (row.est_nav_close / ref_est - 1.0) * 100.0
                if abs(diff) > warn_threshold:
                    _log.warning(
                        "fund_arb 估值偏差 %.2f%%：%s 我方=%.4f 参考=%.4f",
                        diff, fund.fund_code, row.est_nav_close, ref_est,
                    )

            await _upsert_daily(db, fund.fund_code, today,
                                ref_est_nav=ref_est, ref_premium=ref_prem)
        await db.commit()


async def _update_iopv() -> None:
    """从参考网站更新所有基金的 IOPV 历史数据（每日早盘前调用）。"""
    import re
    import subprocess
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()
        existing_iopv = set((await db.execute(
            select(FundArbTrackingDaily.symbol)
            .where(FundArbTrackingDaily.symbol.like("%_iopv"))
            .distinct()
        )).scalars().all())

    for fund in funds:
        iopv_sym = fund.tracking_symbol + "_iopv"
        if iopv_sym not in existing_iopv:
            continue
        exchange = fund.sina_symbol[:2]
        symbol = f"{exchange}{fund.fund_code}"
        url = f"https://www.palmmicro.com/woody/res/{symbol}cn.php"
        try:
            result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=30)
            html = result.stdout
            m = re.search(rf'id="{symbol.upper()}fundhistorytable".*?<tbody>(.*?)</tbody>',
                          html, re.DOTALL | re.IGNORECASE)
            if not m:
                continue
            rows = re.findall(r"<tr>(.*?)</tr>", m.group(1), re.DOTALL)
            async with session_factory() as db:
                for row in rows:
                    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
                    cells_clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                    if len(cells_clean) >= 8 and re.match(r"\d{4}-\d{2}-\d{2}", cells_clean[0]):
                        try:
                            d = dt.date.fromisoformat(cells_clean[0])
                            iopv = float(cells_clean[7])
                            await _upsert_tracking(db, iopv_sym, d, iopv)
                        except (ValueError, IndexError):
                            continue
                await db.commit()
        except Exception:
            _log.exception("fund_arb IOPV 更新失败：%s", fund.fund_code)


async def morning_job() -> None:
    """9:20：汇率中间价 + 美股 ETF 昨收落库 + IOPV 更新。"""
    session_factory = get_sessionmaker()
    today = _now_sh().date()
    try:
        mids = await fetch_fx_mid()
        async with session_factory() as db:
            for sym, price in mids.items():
                await _upsert_tracking(db, sym, today, price)
            await db.commit()
    except Exception:
        _log.exception("fund_arb 中间价抓取失败")
    us_date = today - dt.timedelta(days=1)
    while us_date.weekday() >= 5:
        us_date -= dt.timedelta(days=1)
    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(
                FundArbFund.enabled.is_(True),
                FundArbFund.tracking_symbol.regexp_match(r'^(gb_|hf_)'),
            )
        )).scalars().all()
    symbols = sorted({f.tracking_symbol for f in funds})
    if not symbols:
        return
    try:
        quotes = await get_fetcher().fetch_quotes(symbols)
        async with session_factory() as db:
            for sym, q in quotes.items():
                await _upsert_tracking(db, sym, us_date, q.price)
            await db.commit()
    except Exception:
        _log.exception("fund_arb 美股/国际期货收盘记录失败")
    try:
        await _update_iopv()
    except Exception:
        _log.exception("fund_arb IOPV 批量更新失败")
    try:
        await _calibrate_ref()
    except Exception:
        _log.exception("fund_arb 参考网站校对失败")

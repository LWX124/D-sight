"""盘中实时快照：进程内存单例，所有用户共享；重启/收盘后由 daily 表冷启动兜底。"""
import datetime as dt
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.fund_arb.fetchers import MID_FX_SYMBOL, SPOT_FX_SINA, Quote, QuoteFetcher
from app.fund_arb.models import FundArbDaily, FundArbFactor, FundArbFund, FundArbTrackingDaily
from app.fund_arb.valuation import (
    bond_growth_valuation,
    guard_est_nav,
    index_valuation,
    premium_pct,
    silver_valuation,
)

_log = logging.getLogger(__name__)

R2_THRESHOLD = 0.6
BACKTRACK_DAYS = 5
BOND_GROWTH_WINDOW = 30


@dataclass
class FundSnapshot:
    fund_code: str
    fund_name: str
    category: str
    price: float | None
    price_pct: float | None
    amount: float | None
    est_nav: float | None
    premium: float | None
    nav: float | None
    nav_date: dt.date | None
    err_5d: float | None
    low_confidence: bool
    approx: bool
    purchase_status: str | None
    redemption_status: str | None
    purchase_limit: str | None
    as_of: dt.datetime
    source: str


class SnapshotStore:
    def __init__(self):
        self._snaps: dict[str, FundSnapshot] = {}
        self.as_of: dt.datetime | None = None

    def update(self, snaps: list[FundSnapshot]) -> None:
        for s in snaps:
            self._snaps[s.fund_code] = s
        if snaps:
            self.as_of = max(s.as_of for s in snaps)

    def rows(self, category: str | None = None) -> list[FundSnapshot]:
        out = [
            s for s in self._snaps.values()
            if category is None or s.category == category
        ]
        out.sort(key=lambda s: (s.premium is None, -abs(s.premium or 0.0)))
        return out


_store = SnapshotStore()


def get_store() -> SnapshotStore:
    return _store


async def _load_context(db) -> dict:
    today_sh = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    funds = (await db.execute(
        select(FundArbFund).where(FundArbFund.enabled.is_(True))
    )).scalars().all()
    codes = [f.fund_code for f in funds]
    daily_rows = (await db.execute(
        select(FundArbDaily)
        .where(FundArbDaily.fund_code.in_(codes),
               FundArbDaily.date >= today_sh - dt.timedelta(days=60))
        .order_by(FundArbDaily.fund_code, FundArbDaily.date.desc())
    )).scalars().all()
    nav_anchor: dict[str, FundArbDaily] = {}
    status: dict[str, FundArbDaily] = {}
    errors: dict[str, list[float]] = {}
    navs_series: dict[str, list[FundArbDaily]] = {}
    for r in daily_rows:
        navs_series.setdefault(r.fund_code, []).append(r)
        if r.fund_code not in nav_anchor and r.nav is not None:
            nav_anchor[r.fund_code] = r
        if r.fund_code not in status and r.purchase_status is not None:
            status[r.fund_code] = r
        if r.valuation_error is not None and len(errors.setdefault(r.fund_code, [])) < 5:
            errors[r.fund_code].append(abs(r.valuation_error))
    factor_rows = (await db.execute(
        select(FundArbFactor)
        .where(FundArbFactor.fund_code.in_(codes))
        .order_by(FundArbFactor.fund_code, FundArbFactor.date.desc())
    )).scalars().all()
    factors: dict[str, FundArbFactor] = {}
    for fr in factor_rows:
        factors.setdefault(fr.fund_code, fr)
    tracking_rows = (await db.execute(
        select(FundArbTrackingDaily)
        .where(FundArbTrackingDaily.date >= today_sh - dt.timedelta(days=40))
    )).scalars().all()
    tracking: dict[str, dict[dt.date, float]] = {}
    for tr in tracking_rows:
        tracking.setdefault(tr.symbol, {})[tr.date] = tr.close
    return {
        "funds": funds, "nav_anchor": nav_anchor, "status": status,
        "errors": errors, "factors": factors, "tracking": tracking,
        "navs_series": navs_series, "today": today_sh,
    }


def _base_close(tracking: dict[dt.date, float], target: dt.date) -> float | None:
    for back in range(BACKTRACK_DAYS + 1):
        d = target - dt.timedelta(days=back)
        if d in tracking:
            return tracking[d]
    return None


def _estimate(fund: FundArbFund, ctx: dict, quotes: dict[str, Quote]) -> float | None:
    anchor = ctx["nav_anchor"].get(fund.fund_code)
    if anchor is None or anchor.nav is None:
        return None
    nav_base, nav_date = anchor.nav, anchor.date
    if fund.valuation_method == "silver_future":
        q = quotes.get(fund.tracking_symbol)
        if q is None or q.prev_settle is None:
            return None
        return silver_valuation(nav_base, q.price, q.prev_settle)
    if fund.valuation_method == "bond_growth":
        series = [r for r in ctx["navs_series"].get(fund.fund_code, []) if r.nav is not None]
        if len(series) < 2:
            return None
        newest, oldest = series[0], series[min(len(series) - 1, BOND_GROWTH_WINDOW)]
        span = (newest.date - oldest.date).days
        if span <= 0:
            return None
        daily_growth = (newest.nav / oldest.nav - 1.0) / span
        days = (ctx["today"] - newest.date).days
        return bond_growth_valuation(newest.nav, daily_growth, max(days, 0))
    # index 公式
    q_track = quotes.get(fund.tracking_symbol)
    idx_base = _base_close(ctx["tracking"].get(fund.tracking_symbol, {}), nav_date)
    if q_track is None or idx_base is None:
        return None
    fx_t = fx_base = 1.0
    if fund.currency:
        mid_symbol = MID_FX_SYMBOL[fund.currency]
        fx_base = _base_close(ctx["tracking"].get(mid_symbol, {}), nav_date)
        spot = quotes.get(SPOT_FX_SINA[fund.currency])
        if fund.rate_type == "spot":
            if spot is None:
                return None
            fx_t = spot.price
        else:
            fx_t = spot.price if spot is not None else _base_close(
                ctx["tracking"].get(mid_symbol, {}), ctx["today"]
            )
        if fx_base is None or fx_t is None:
            return None
    factor = ctx["factors"].get(fund.fund_code)
    if factor is not None and factor.r_squared >= R2_THRESHOLD:
        position = factor.position_beta
    else:
        position = fund.pos_ratio_default
    return index_valuation(nav_base, position, q_track.price, idx_base, fx_t, fx_base)


async def rebuild_snapshots(session_factory, fetcher: QuoteFetcher,
                            now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.UTC)
    async with session_factory() as db:
        ctx = await _load_context(db)
    symbols: set[str] = set()
    for f in ctx["funds"]:
        symbols.add(f.sina_symbol)
        if f.tracking_symbol != "-":
            symbols.add(f.tracking_symbol)
        if f.currency:
            symbols.add(SPOT_FX_SINA[f.currency])
    try:
        quotes = await fetcher.fetch_quotes(sorted(symbols))
    except Exception:
        _log.exception("fund_arb 行情批量抓取失败")
        return 0
    snaps, ok = [], 0
    for fund in ctx["funds"]:
        try:
            q_price = quotes.get(fund.sina_symbol)
            est = _estimate(fund, ctx, quotes)
            anchor = ctx["nav_anchor"].get(fund.fund_code)
            if est is not None and anchor is not None:
                est = guard_est_nav(est, anchor.nav)
            prem = (
                premium_pct(q_price.price, est)
                if q_price is not None and est is not None else None
            )
            if est is not None:
                ok += 1
            errs = ctx["errors"].get(fund.fund_code, [])
            factor = ctx["factors"].get(fund.fund_code)
            status_row = ctx["status"].get(fund.fund_code)
            snaps.append(FundSnapshot(
                fund_code=fund.fund_code, fund_name=fund.fund_name,
                category=fund.category,
                price=q_price.price if q_price else None,
                price_pct=q_price.pct if q_price else None,
                amount=None,
                est_nav=round(est, 4) if est is not None else None,
                premium=round(prem, 3) if prem is not None else None,
                nav=anchor.nav if anchor else None,
                nav_date=anchor.date if anchor else None,
                err_5d=round(sum(errs) / len(errs), 3) if errs else None,
                low_confidence=bool(
                    (factor is not None and factor.r_squared < R2_THRESHOLD)
                    or (errs and sum(errs) / len(errs) > 1.0)
                ),
                approx=fund.approx,
                purchase_status=status_row.purchase_status if status_row else None,
                redemption_status=status_row.redemption_status if status_row else None,
                purchase_limit=status_row.purchase_limit if status_row else None,
                as_of=now, source="realtime",
            ))
        except Exception:
            _log.exception("fund_arb 估值失败：%s", fund.fund_code)
    get_store().update(snaps)
    return ok


async def load_close_snapshots(session_factory) -> int:
    now = dt.datetime.now(dt.UTC)
    async with session_factory() as db:
        ctx = await _load_context(db)
    snaps = []
    for fund in ctx["funds"]:
        series = ctx["navs_series"].get(fund.fund_code, [])
        if not series:
            continue
        latest = series[0]
        anchor = ctx["nav_anchor"].get(fund.fund_code)
        errs = ctx["errors"].get(fund.fund_code, [])
        status_row = ctx["status"].get(fund.fund_code)
        snaps.append(FundSnapshot(
            fund_code=fund.fund_code, fund_name=fund.fund_name, category=fund.category,
            price=latest.price, price_pct=latest.price_pct, amount=latest.amount,
            est_nav=latest.est_nav_close, premium=latest.premium,
            nav=anchor.nav if anchor else None,
            nav_date=anchor.date if anchor else None,
            err_5d=round(sum(errs) / len(errs), 3) if errs else None,
            low_confidence=bool(
                (ctx["factors"].get(fund.fund_code) is not None and
                 ctx["factors"][fund.fund_code].r_squared < R2_THRESHOLD)
                or (errs and sum(errs) / len(errs) > 1.0)
            ),
            approx=fund.approx,
            purchase_status=status_row.purchase_status if status_row else None,
            redemption_status=status_row.redemption_status if status_row else None,
            purchase_limit=status_row.purchase_limit if status_row else None,
            as_of=now, source="close",
        ))
    get_store().update(snaps)
    return len(snaps)

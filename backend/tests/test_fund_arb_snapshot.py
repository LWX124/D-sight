import datetime as dt

import pytest

from app.core.db import get_sessionmaker
from app.fund_arb.fetchers import FakeQuoteFetcher, Quote
from app.fund_arb.models import FundArbDaily, FundArbFund, FundArbTrackingDaily
from app.fund_arb.snapshot import FundSnapshot, get_store, load_close_snapshots, rebuild_snapshots


async def _setup_fund(db, code="513000", add_tracking=True, **kw):
    defaults = dict(
        fund_code=code, fund_name="测试日经", category="qdii_japan",
        sina_symbol="sh513000", tracking_symbol="int_nikkei", tracking_type="index",
        currency="JPY", rate_type="mid", valuation_method="index",
        nav_field="dwjz", pos_ratio_default=0.95, approx=False, enabled=True,
    )
    defaults.update(kw)
    db.add(FundArbFund(**defaults))
    nav_date = dt.date(2026, 7, 17)
    db.add(FundArbDaily(date=nav_date, fund_code=code, nav=1.0))
    if add_tracking:
        db.add(FundArbTrackingDaily(date=nav_date, symbol="int_nikkei", close=40000.0))
        db.add(FundArbTrackingDaily(date=nav_date, symbol="JPYCNY_MID", close=0.048))
    await db.commit()
    return nav_date


@pytest.mark.asyncio
async def test_rebuild_index_fund(db_session):
    await _setup_fund(db_session, code="513000")
    fetcher = FakeQuoteFetcher({
        "sh513000": Quote(symbol="sh513000", price=1.06, prev_close=1.03, pct=2.91),
        "int_nikkei": Quote(symbol="int_nikkei", price=40800.0),
        "fx_sjpycny": Quote(symbol="fx_sjpycny", price=0.048),
    })
    n = await rebuild_snapshots(get_sessionmaker(), fetcher)
    assert n >= 1
    snap = {s.fund_code: s for s in get_store().rows()}["513000"]
    assert snap.est_nav == pytest.approx(1.019, rel=1e-3)
    assert snap.premium == pytest.approx((1.06 / 1.019 - 1) * 100, rel=1e-2)
    assert snap.nav_date == dt.date(2026, 7, 17)
    assert snap.source == "realtime"


@pytest.mark.asyncio
async def test_spot_rate_missing_skips_fund(db_session):
    await _setup_fund(db_session, code="513350", rate_type="spot", currency="USD",
                      sina_symbol="sh513350", tracking_symbol="gb_spy",
                      add_tracking=False)
    async with get_sessionmaker()() as db:
        db.add(FundArbTrackingDaily(date=dt.date(2026, 7, 17), symbol="gb_spy", close=560.0))
        db.add(FundArbTrackingDaily(date=dt.date(2026, 7, 17), symbol="USDCNY_MID", close=7.17))
        await db.commit()
    fetcher = FakeQuoteFetcher({
        "sh513350": Quote(symbol="sh513350", price=2.0, prev_close=1.9, pct=5.26),
        "gb_spy": Quote(symbol="gb_spy", price=565.0),
    })
    await rebuild_snapshots(get_sessionmaker(), fetcher)
    snap = {s.fund_code: s for s in get_store().rows()}["513350"]
    assert snap.est_nav is None and snap.premium is None
    assert snap.price == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_base_close_backtrack(db_session):
    nav_date = dt.date(2026, 7, 14)
    async with get_sessionmaker()() as db:
        db.add(FundArbFund(
            fund_code="161125", fund_name="标普测试", category="qdii_us_eu",
            sina_symbol="sz161125", tracking_symbol="gb_spy", tracking_type="us_etf",
            currency="USD", rate_type="mid", valuation_method="index",
            nav_field="dwjz", pos_ratio_default=0.9, approx=False, enabled=True,
        ))
        db.add(FundArbDaily(date=nav_date, fund_code="161125", nav=2.0))
        db.add(FundArbTrackingDaily(date=dt.date(2026, 7, 12), symbol="gb_spy", close=560.0))
        db.add(FundArbTrackingDaily(date=dt.date(2026, 7, 12), symbol="USDCNY_MID", close=7.17))
        db.add(FundArbTrackingDaily(date=nav_date, symbol="USDCNY_MID", close=7.17))
        await db.commit()
    fetcher = FakeQuoteFetcher({
        "sz161125": Quote(symbol="sz161125", price=2.1, prev_close=2.05, pct=2.44),
        "gb_spy": Quote(symbol="gb_spy", price=571.2),
        "fx_susdcny": Quote(symbol="fx_susdcny", price=7.17),
    })
    await rebuild_snapshots(get_sessionmaker(), fetcher)
    snap = {s.fund_code: s for s in get_store().rows()}["161125"]
    assert snap.est_nav == pytest.approx(2.0 * (1 + 0.9 * 0.02), rel=1e-3)


@pytest.mark.asyncio
async def test_cold_start_from_daily(db_session):
    d = dt.date(2026, 7, 18)
    async with get_sessionmaker()() as db:
        db.add(FundArbFund(
            fund_code="161226", fund_name="白银测试", category="silver",
            sina_symbol="sz161226", tracking_symbol="nf_AG0", tracking_type="future",
            currency=None, rate_type="mid", valuation_method="silver_future",
            nav_field="dwjz", pos_ratio_default=0.95, approx=False, enabled=True,
        ))
        db.add(FundArbDaily(
            date=d, fund_code="161226", price=1.31, price_pct=0.5,
            nav=1.28, est_nav_close=1.29, premium=1.55,
        ))
        await db.commit()
    n = await load_close_snapshots(get_sessionmaker())
    assert n >= 1
    snap = {s.fund_code: s for s in get_store().rows("silver")}["161226"]
    assert snap.source == "close"
    assert snap.premium == pytest.approx(1.55)


@pytest.mark.asyncio
async def test_rows_sorted_by_abs_premium(db_session):
    now = dt.datetime.now(dt.UTC)
    mk = lambda code, prem: FundSnapshot(
        fund_code=code, fund_name=code, category="domestic_lof", price=1.0,
        price_pct=0.0, amount=None, est_nav=1.0, premium=prem, nav=1.0,
        nav_date=None, err_5d=None, low_confidence=False, approx=False,
        purchase_status=None, redemption_status=None, purchase_limit=None,
        as_of=now, source="realtime",
    )
    get_store().update([mk("a", 0.5), mk("b", -3.0), mk("c", None), mk("d", 2.0)])
    codes = [s.fund_code for s in get_store().rows("domestic_lof")]
    assert codes == ["b", "d", "a", "c"]

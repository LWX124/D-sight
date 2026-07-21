import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.fund_arb import job as fund_job
from app.fund_arb.fetchers import FakeQuoteFetcher, NavRecord, Quote
from app.fund_arb.job import evening_pipeline, is_market_open, snapshot_tick
from app.fund_arb.models import FundArbDaily, FundArbFactor, FundArbFund, FundArbTrackingDaily

SH = ZoneInfo("Asia/Shanghai")


def test_is_market_open():
    assert is_market_open(dt.datetime(2026, 7, 20, 10, 0, tzinfo=SH))
    assert not is_market_open(dt.datetime(2026, 7, 20, 8, 0, tzinfo=SH))
    assert not is_market_open(dt.datetime(2026, 7, 20, 15, 30, tzinfo=SH))
    assert not is_market_open(dt.datetime(2026, 7, 19, 10, 0, tzinfo=SH))
    assert not is_market_open(dt.datetime(2026, 10, 1, 10, 0, tzinfo=SH))


@pytest.mark.asyncio
async def test_snapshot_tick_closed_market_noop(monkeypatch):
    monkeypatch.setattr(fund_job, "_now_sh", lambda: dt.datetime(2026, 7, 19, 10, 0, tzinfo=SH))
    assert await snapshot_tick() == 0


@pytest.mark.asyncio
async def test_snapshot_tick_persists_close(db_session, monkeypatch):
    async with get_sessionmaker()() as db:
        db.add(FundArbFund(
            fund_code="501300", fund_name="职测LOF", category="domestic_lof",
            sina_symbol="sh501300", tracking_symbol="sh000300", tracking_type="index",
            currency=None, rate_type="mid", valuation_method="index",
            nav_field="dwjz", pos_ratio_default=0.95, approx=False, enabled=True,
        ))
        d = dt.date(2026, 7, 10)
        db.add(FundArbDaily(date=d, fund_code="501300", nav=1.5))
        db.add(FundArbTrackingDaily(date=d, symbol="sh000300", close=4500.0))
        await db.commit()
    fetcher = FakeQuoteFetcher({
        "sh501300": Quote(symbol="sh501300", price=1.58, prev_close=1.55, pct=1.94),
        "sh000300": Quote(symbol="sh000300", price=4590.0, prev_close=4500.0, pct=2.0),
    })
    monkeypatch.setattr(fund_job, "get_fetcher", lambda: fetcher)
    monkeypatch.setattr(fund_job, "_now_sh", lambda: dt.datetime(2026, 7, 20, 15, 1, tzinfo=SH))
    n = await snapshot_tick()
    assert n >= 1
    async with get_sessionmaker()() as db:
        row = (await db.execute(select(FundArbDaily).where(
            FundArbDaily.fund_code == "501300", FundArbDaily.date == dt.date(2026, 7, 20)
        ))).scalar_one()
    assert row.price == pytest.approx(1.58)
    assert row.est_nav_close is not None and row.premium is not None
    await snapshot_tick()


@pytest.mark.asyncio
async def test_evening_pipeline(db_session, monkeypatch):
    code = "501302"
    base = dt.date(2026, 6, 25)
    async with get_sessionmaker()() as db:
        db.add(FundArbFund(
            fund_code=code, fund_name="职测LOF2", category="domestic_lof",
            sina_symbol="sh501302", tracking_symbol="sh000905", tracking_type="index",
            currency=None, rate_type="mid", valuation_method="index",
            nav_field="dwjz", pos_ratio_default=0.95, approx=False, enabled=True,
        ))
        db.add(FundArbDaily(date=dt.date(2026, 6, 30), fund_code=code,
                            price=1.52, est_nav_close=1.505, premium=1.0))
        for i in range(13):
            db.add(FundArbTrackingDaily(
                date=base + dt.timedelta(days=i), symbol="sh000905",
                close=4400.0 * (1.003 ** i),
            ))
        await db.commit()

    async def fake_nav_history(fund_code: str, count: int = 60):
        out = []
        for i in range(13):
            out.append(NavRecord(
                date=base + dt.timedelta(days=i),
                nav=round(1.5 * (1.00285 ** i), 6), acc_nav=None, dividend=None,
            ))
        out.reverse()
        return out

    async def fake_purchase_status():
        return {code: {"purchase_status": "开放申购",
                       "redemption_status": "开放赎回",
                       "purchase_limit": "1000"}}

    monkeypatch.setattr(fund_job, "fetch_nav_history", fake_nav_history)
    monkeypatch.setattr(fund_job, "fetch_purchase_status", fake_purchase_status)
    monkeypatch.setattr(fund_job, "get_fetcher", lambda: FakeQuoteFetcher({
        "sh000905": Quote(symbol="sh000905", price=4580.0, prev_close=4560.0, pct=0.44),
    }))
    monkeypatch.setattr(fund_job, "_now_sh", lambda: dt.datetime(2026, 7, 20, 18, 0, tzinfo=SH))
    await evening_pipeline()
    async with get_sessionmaker()() as db:
        factor = (await db.execute(select(FundArbFactor).where(
            FundArbFactor.fund_code == code
        ))).scalars().first()
        assert factor is not None
        assert 0.8 < factor.position_beta < 1.1

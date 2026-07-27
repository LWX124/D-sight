import datetime as dt

import pytest
from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.fund_arb import bootstrap as bs
from app.fund_arb.fetchers import DatedPrice, NavRecord
from app.fund_arb.models import FundArbDaily, FundArbFund, FundArbTrackingDaily


@pytest.mark.asyncio
async def test_bootstrap_fills_history(db_session, monkeypatch):
    async with get_sessionmaker()() as db:
        db.add(FundArbFund(
            fund_code="513520", fund_name="日经测试", category="qdii_japan",
            sina_symbol="sh513520", tracking_symbol="int_nikkei", tracking_type="index",
            currency="JPY", rate_type="mid", valuation_method="index",
            nav_field="dwjz", pos_ratio_default=0.95, approx=False, enabled=True,
        ))
        await db.commit()

    async def fake_nav(code, count=60):
        today = dt.date.today()
        return [NavRecord(date=today - dt.timedelta(days=i),
                          nav=1.0 + i * 0.001, acc_nav=None, dividend=None)
                for i in range(count)]

    async def fake_symbol_history(symbol, days):
        today = dt.date.today()
        return {today - dt.timedelta(days=i): 40000.0 - i * 10
                for i in range(days)}

    async def fake_fx_history(days):
        today = dt.date.today()
        return {"JPYCNY_MID": {today - dt.timedelta(days=i): 0.048
                               for i in range(days)}}

    async def fake_lbma_empty(limit=1):
        return []

    monkeypatch.setattr(bs, "fetch_nav_history", fake_nav)
    monkeypatch.setattr(bs, "_fetch_symbol_history", fake_symbol_history)
    monkeypatch.setattr(bs, "_fetch_fx_mid_history", fake_fx_history)
    monkeypatch.setattr(bs, "fetch_lbma_gold_pm", fake_lbma_empty)

    stats = await bs.run_bootstrap(days=30)
    assert stats["navs"] > 0 and stats["tracking"] > 0
    async with get_sessionmaker()() as db:
        n_nav = (await db.execute(select(func.count()).select_from(FundArbDaily)
                                  .where(FundArbDaily.fund_code == "513520"))).scalar_one()
        n_trk = (await db.execute(select(func.count()).select_from(FundArbTrackingDaily)
                                  .where(FundArbTrackingDaily.symbol == "int_nikkei"))).scalar_one()
    assert n_nav >= 30 and n_trk >= 30
    stats2 = await bs.run_bootstrap(days=30)
    assert stats2["navs"] == stats["navs"]


@pytest.mark.asyncio
async def test_bootstrap_backfills_lbma_with_source_dates(db_session, monkeypatch):
    today = dt.date.today()
    source_rows = [
        DatedPrice(date=today - dt.timedelta(days=3), price=4000.0),
        DatedPrice(date=today - dt.timedelta(days=2), price=4010.0),
    ]

    async def fake_lbma(limit=1):
        assert limit is None
        return source_rows

    async def fake_fx_history(days):
        return {}

    monkeypatch.setattr(bs, "fetch_lbma_gold_pm", fake_lbma)
    monkeypatch.setattr(bs, "_fetch_fx_mid_history", fake_fx_history)

    stats = await bs.run_bootstrap(days=30)

    assert stats["lbma"] == 2
    async with get_sessionmaker()() as db:
        rows = (await db.execute(
            select(FundArbTrackingDaily)
            .where(FundArbTrackingDaily.symbol == "LBMA_GOLD_PM")
            .order_by(FundArbTrackingDaily.date)
        )).scalars().all()
    assert [(row.date, row.close) for row in rows] == [
        (source_rows[0].date, 4000.0),
        (source_rows[1].date, 4010.0),
    ]

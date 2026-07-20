import datetime as dt

import pytest
from sqlalchemy import select

from app.fund_arb.models import (
    FundArbDaily,
    FundArbFactor,
    FundArbFund,
    FundArbTrackingDaily,
)


@pytest.mark.asyncio
async def test_fund_and_daily_roundtrip(db_session):
    fund = FundArbFund(
        fund_code="161129", fund_name="易方达原油", category="gold_oil",
        sina_symbol="sz161129", tracking_symbol="gb_uso", tracking_type="us_etf",
        currency="USD", rate_type="mid", valuation_method="index",
        nav_field="dwjz", pos_ratio_default=0.9, approx=True, enabled=True,
    )
    db_session.add(fund)
    today = dt.date(2026, 7, 20)
    db_session.add(FundArbDaily(
        date=today, fund_code="161129", price=1.05, price_pct=1.2,
        amount=12345678.0, nav=1.0, est_nav_close=1.01, premium=3.96,
    ))
    db_session.add(FundArbFactor(
        fund_code="161129", date=today, position_beta=0.92, r_squared=0.98, sample_days=20,
    ))
    db_session.add(FundArbTrackingDaily(date=today, symbol="USDCNY_MID", close=7.17))
    await db_session.commit()

    row = (await db_session.execute(
        select(FundArbDaily).where(FundArbDaily.fund_code == "161129")
    )).scalar_one()
    assert row.premium == pytest.approx(3.96)
    assert row.valuation_error is None  # 盘后回填前为空


@pytest.mark.asyncio
async def test_daily_unique_constraint(db_session):
    from sqlalchemy.exc import IntegrityError

    d = dt.date(2026, 7, 21)
    db_session.add(FundArbDaily(date=d, fund_code="501018", price=1.0))
    await db_session.commit()
    db_session.add(FundArbDaily(date=d, fund_code="501018", price=1.1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

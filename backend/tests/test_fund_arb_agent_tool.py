import datetime as dt

import pytest

from app.agent.tools.fund_arb import make_fund_arb_query
from app.fund_arb.snapshot import FundSnapshot, get_store


def _snap(code, category="qdii_us_eu", premium=2.5):
    return FundSnapshot(
        fund_code=code, fund_name=f"基金{code}", category=category, price=1.05,
        price_pct=1.2, amount=None, est_nav=1.024, premium=premium, nav=1.0,
        nav_date=dt.date(2026, 7, 17), err_5d=0.2, low_confidence=False, approx=False,
        purchase_status="开放申购", redemption_status="开放赎回", purchase_limit="50万",
        as_of=dt.datetime.now(dt.UTC), source="realtime",
    )


@pytest.mark.asyncio
async def test_query_by_threshold():
    get_store().update([_snap("161125", premium=3.0), _snap("161130", premium=0.5)])
    tool = make_fund_arb_query()
    out = await tool.ainvoke({"category": "qdii_us_eu", "min_premium": 2.0})
    assert "161125" in out and "161130" not in out


@pytest.mark.asyncio
async def test_query_by_code():
    get_store().update([_snap("161125", premium=3.0)])
    tool = make_fund_arb_query()
    out = await tool.ainvoke({"code": "161125"})
    assert "161125" in out and "开放申购" in out


@pytest.mark.asyncio
async def test_query_empty():
    tool = make_fund_arb_query()
    out = await tool.ainvoke({"category": "silver", "min_premium": 99.0})
    assert "无" in out

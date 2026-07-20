import datetime as dt

import pytest

from app.core.db import get_sessionmaker
from app.fund_arb.models import FundArbDaily, FundArbFund
from app.fund_arb.snapshot import FundSnapshot, get_store


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


def _snap(code="161129", premium=2.5):
    return FundSnapshot(
        fund_code=code, fund_name="测试基金", category="gold_oil", price=1.05,
        price_pct=1.2, amount=None, est_nav=1.024, premium=premium, nav=1.0,
        nav_date=dt.date(2026, 7, 17), err_5d=0.15, low_confidence=False, approx=True,
        purchase_status="限大额", redemption_status="开放赎回", purchase_limit="1000",
        as_of=dt.datetime.now(dt.UTC), source="realtime",
    )


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client):
    r = await client.get("/api/fund-arb/dashboard")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_returns_snapshots(client, registered_user):
    get_store().update([_snap()])
    r = await client.get("/api/fund-arb/dashboard?category=gold_oil",
                         headers=_auth(registered_user))
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["fund_code"] == "161129"
    assert body["rows"][0]["premium"] == pytest.approx(2.5)
    assert body["rows"][0]["nav_date"] == "2026-07-17"
    assert isinstance(body["market_open"], bool)


@pytest.mark.asyncio
async def test_history(client, registered_user):
    async with get_sessionmaker()() as db:
        db.add(FundArbFund(
            fund_code="160719", fund_name="嘉实黄金", category="gold_oil",
            sina_symbol="sz160719", tracking_symbol="gb_gld", tracking_type="us_etf",
            currency="USD", rate_type="mid", valuation_method="index",
            nav_field="dwjz", pos_ratio_default=0.9, approx=True, enabled=True,
        ))
        for i in range(3):
            db.add(FundArbDaily(
                date=dt.date(2026, 7, 15 + i), fund_code="160719",
                price=1.0 + i * 0.01, nav=1.0, premium=i * 1.0, valuation_error=0.1,
            ))
        await db.commit()
    r = await client.get("/api/fund-arb/funds/160719/history?days=30",
                         headers=_auth(registered_user))
    assert r.status_code == 200
    pts = r.json()["points"]
    assert len(pts) == 3
    assert pts[0]["date"] < pts[-1]["date"]


@pytest.mark.asyncio
async def test_refresh_admin_only(client, registered_user):
    r = await client.post("/api/fund-arb/refresh", headers=_auth(registered_user))
    assert r.status_code == 403

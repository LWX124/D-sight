import pytest
from sqlalchemy import func, select

from app.fund_arb.models import FundArbFund
from app.fund_arb.seed import seed_funds

VALID_CATEGORIES = {
    "gold_oil", "qdii_us_eu", "qdii_japan", "qdii_asia",
    "domestic_lof", "silver", "cash_bond",
}


@pytest.mark.asyncio
async def test_seed_funds_idempotent(db_session):
    n1 = await seed_funds(db_session)
    assert n1 > 30
    n2 = await seed_funds(db_session)
    assert n2 == n1
    total = (await db_session.execute(
        select(func.count()).select_from(FundArbFund)
    )).scalar_one()
    assert total == n1


@pytest.mark.asyncio
async def test_seed_data_valid(db_session):
    await seed_funds(db_session)
    rows = (await db_session.execute(select(FundArbFund))).scalars().all()
    for r in rows:
        assert r.category in VALID_CATEGORIES
        assert 0 < r.pos_ratio_default <= 1.2
        assert r.valuation_method in {"index", "silver_future", "bond_growth"}
        if r.valuation_method == "index":
            assert r.tracking_symbol.startswith(("sh", "sz", "gb_", "int_", "rt_", "nf_")), (
                f"{r.fund_code} tracking_symbol 未校对: {r.tracking_symbol}"
            )

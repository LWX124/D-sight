import pytest

from app.fund_arb.valuation import (
    bond_growth_valuation,
    guard_est_nav,
    index_valuation,
    premium_pct,
    silver_valuation,
)


def test_index_valuation_basic():
    # 净值1.0，仓位0.95，指数涨1%，汇率不变 → 1.0095
    assert index_valuation(1.0, 0.95, 101.0, 100.0) == pytest.approx(1.0095)


def test_index_valuation_with_fx():
    # 指数涨1% 且汇率升0.5%：净比率 = 0.95*(1.01*1.005-1)
    expected = 1.0 * (1 + 0.95 * (1.01 * 1.005 - 1))
    assert index_valuation(1.0, 0.95, 101.0, 100.0, 7.2360, 7.2000) == pytest.approx(
        expected, rel=1e-9
    )


def test_index_valuation_domestic_no_fx():
    # 国内 LOF 汇率项缺省 1.0
    assert index_valuation(2.0, 0.9, 99.0, 100.0) == pytest.approx(2.0 * (1 + 0.9 * -0.01))


def test_index_valuation_invalid_base():
    with pytest.raises(ValueError):
        index_valuation(1.0, 0.95, 101.0, 0.0)
    with pytest.raises(ValueError):
        index_valuation(1.0, 0.95, 101.0, 100.0, 7.2, 0.0)


def test_silver_valuation():
    # est = nav * (AG0现价/AG0昨结算)
    assert silver_valuation(1.0, 9180.0, 9000.0) == pytest.approx(1.02)
    with pytest.raises(ValueError):
        silver_valuation(1.0, 9180.0, 0.0)


def test_bond_growth_valuation():
    # 日均增长 0.0001，3 个自然日
    assert bond_growth_valuation(100.0, 0.0001, 3) == pytest.approx(100.03)


def test_premium_pct():
    assert premium_pct(1.05, 1.0) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        premium_pct(1.05, 0.0)


def test_guard_est_nav_fallback():
    # 偏离 >50% 回退净值（arbTest 防御规则）
    assert guard_est_nav(2.0, 1.0) == 1.0
    assert guard_est_nav(1.2, 1.0) == 1.2

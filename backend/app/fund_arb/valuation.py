"""估值公式（纯函数，无 IO）。公式体系源自 arbTest docs/003 权威指南。

铁律：溢价只锚最新可得官方净值；估值与净值偏离 >50% 回退净值。
"""


def index_valuation(
    nav_base: float,
    position: float,
    idx_t: float,
    idx_base: float,
    fx_t: float = 1.0,
    fx_base: float = 1.0,
) -> float:
    """指数公式：est = nav × (1 + position × (idx_t/idx_base × fx_t/fx_base − 1))。

    国内 LOF 汇率项恒为 1（缺省值即可）。
    """
    if idx_base <= 0 or fx_base <= 0:
        raise ValueError("idx_base/fx_base 必须为正")
    net_ratio = position * ((idx_t / idx_base) * (fx_t / fx_base) - 1.0)
    return nav_base * (1.0 + net_ratio)


def silver_valuation(nav_base: float, ag0_price: float, ag0_prev_settle: float) -> float:
    """白银 161226：est = nav × (AG0 实时价 / AG0 昨结算价)。"""
    if ag0_prev_settle <= 0:
        raise ValueError("ag0_prev_settle 必须为正")
    return nav_base * (ag0_price / ag0_prev_settle)


def bond_growth_valuation(nav_latest: float, daily_growth: float, days: int) -> float:
    """债券/现金类：est = nav × (1 + 日均增长 × 自然日数)。"""
    return nav_latest * (1.0 + daily_growth * days)


def premium_pct(price: float, est_nav: float) -> float:
    """溢价率（%）= (价格/估值 − 1) × 100。"""
    if est_nav <= 0:
        raise ValueError("est_nav 必须为正")
    return (price / est_nav - 1.0) * 100.0


def guard_est_nav(est_nav: float, nav_base: float) -> float:
    """防御：估值与净值偏离 >50% 时回退净值（arbTest 实盘教训）。"""
    if nav_base > 0 and abs(est_nav / nav_base - 1.0) > 0.5:
        return nav_base
    return est_nav

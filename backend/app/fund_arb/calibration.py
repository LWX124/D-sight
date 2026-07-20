"""滚动回归仓位校准：穷人版 Woody position 因子。

近 N 个交易日过原点最小二乘：r_nav ≈ β × r_track，β 即有效仓位。
分红/拆分防御：|r_nav − r_track| > outlier_threshold 的样本剔除。
"""


def calibrate_position(
    nav_returns: list[float],
    track_returns: list[float],
    min_samples: int = 10,
    outlier_threshold: float = 0.05,
) -> tuple[float, float] | None:
    """返回 (position_beta, r_squared)；样本不足或标的零方差返回 None。

    beta clamp 到 [0, 1.2]（基金仓位物理上限附近，防脏数据）。
    """
    pairs = [
        (rn, rt)
        for rn, rt in zip(nav_returns, track_returns, strict=True)
        if abs(rn - rt) <= outlier_threshold
    ]
    if len(pairs) < min_samples:
        return None
    ss_tt = sum(rt * rt for _, rt in pairs)
    if ss_tt <= 0:
        return None
    beta = sum(rn * rt for rn, rt in pairs) / ss_tt
    ss_res = sum((rn - beta * rt) ** 2 for rn, rt in pairs)
    ss_tot = sum(rn * rn for rn, _ in pairs)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    beta = min(max(beta, 0.0), 1.2)
    return beta, r_squared

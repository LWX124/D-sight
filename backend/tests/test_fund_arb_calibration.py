import pytest

from app.fund_arb.calibration import calibrate_position


def test_perfect_beta():
    track = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, -0.005, 0.008, 0.012, -0.015]
    nav = [r * 0.95 for r in track]  # 真实仓位 0.95
    result = calibrate_position(nav, track)
    assert result is not None
    beta, r2 = result
    assert beta == pytest.approx(0.95, abs=1e-6)
    assert r2 == pytest.approx(1.0, abs=1e-6)


def test_insufficient_samples():
    assert calibrate_position([0.01] * 5, [0.01] * 5) is None


def test_outlier_excluded():
    # 10 个正常样本 + 1 个分红跳变样本（|r_nav − r_track| > 5%），剔除后仍应得 0.9
    track = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, -0.005, 0.008, 0.012, -0.015, 0.01]
    nav = [r * 0.9 for r in track]
    nav[10] = -0.08  # 分红除息日：净值大跌但指数微涨
    result = calibrate_position(nav, track)
    assert result is not None
    beta, _ = result
    assert beta == pytest.approx(0.9, abs=1e-6)


def test_outliers_reduce_below_min_samples():
    # 全部样本都是异常 → 剔除后不足 → None
    track = [0.001] * 12
    nav = [0.2] * 12
    assert calibrate_position(nav, track) is None


def test_beta_clamped():
    # 杠杆异常数据 clamp 到 [0, 1.2]
    track = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, -0.005, 0.008, 0.012, -0.015]
    nav = [r * 3.0 for r in track]  # 夹杂在 outlier 阈值内的小收益
    nav = [min(max(v, -0.04), 0.04) for v in nav]
    result = calibrate_position(nav, track)
    if result is not None:
        beta, _ = result
        assert 0.0 <= beta <= 1.2


def test_zero_track_variance():
    assert calibrate_position([0.01] * 10, [0.0] * 10) is None

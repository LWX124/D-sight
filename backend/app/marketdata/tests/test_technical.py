"""技术指标纯函数测试：无网络，验证数值正确性与"样本不足即不产出"。"""

from datetime import date, timedelta

import pytest

from app.marketdata import technical as tech
from app.marketdata.schemas import Bar, DailyBars


def make_bars(closes: list[float], highs=None, lows=None, volumes=None) -> DailyBars:
    start = date(2026, 1, 1)
    bars = [
        Bar(
            date=start + timedelta(days=i),
            open=close,
            high=(highs[i] if highs else close * 1.01),
            low=(lows[i] if lows else close * 0.99),
            close=close,
            volume=(volumes[i] if volumes else 1000.0),
        )
        for i, close in enumerate(closes)
    ]
    return DailyBars(symbol="600519", bars=bars, source="test")


class TestSMA:
    def test_matches_manual_average(self):
        assert tech.sma([1, 2, 3, 4, 5], 5) == 3.0

    def test_uses_only_last_window(self):
        assert tech.sma([100, 1, 2, 3], 3) == 2.0

    def test_returns_none_when_sample_too_short(self):
        assert tech.sma([1, 2], 5) is None


class TestRSI:
    def test_all_gains_gives_100(self):
        assert tech.rsi(list(range(1, 20)), 14) == 100.0

    def test_all_losses_gives_0(self):
        assert tech.rsi(list(range(20, 1, -1)), 14) == 0.0

    def test_within_bounds(self):
        closes = [10, 11, 10.5, 12, 11.5, 13, 12.5, 14, 13, 15, 14.5, 16, 15, 17, 16.5]
        value = tech.rsi(closes, 14)
        assert 0 < value < 100

    def test_returns_none_when_sample_too_short(self):
        assert tech.rsi([1, 2, 3], 14) is None


class TestMACD:
    def test_uptrend_is_positive(self):
        assert tech.macd([float(i) for i in range(1, 60)]) > 0

    def test_downtrend_is_negative(self):
        assert tech.macd([float(i) for i in range(60, 1, -1)]) < 0

    def test_returns_none_when_sample_too_short(self):
        assert tech.macd([1.0, 2.0, 3.0]) is None


class TestBollinger:
    def test_flat_series_collapses_to_price(self):
        upper, lower = tech.bollinger([10.0] * 20)
        assert upper == lower == 10.0

    def test_band_brackets_mean(self):
        upper, lower = tech.bollinger([float(i) for i in range(1, 21)])
        assert lower < 10.5 < upper

    def test_returns_none_pair_when_short(self):
        assert tech.bollinger([1.0, 2.0]) == (None, None)


class TestVolatility:
    def test_flat_series_is_zero(self):
        assert tech.volatility([10.0] * 30, 20) == pytest.approx(0.0)

    def test_volatile_series_is_larger(self):
        calm = tech.volatility([10 + 0.01 * (i % 2) for i in range(30)], 20)
        wild = tech.volatility([10 + 2.0 * (i % 2) for i in range(30)], 20)
        assert wild > calm

    def test_returns_none_when_sample_too_short(self):
        assert tech.volatility([1.0] * 5, 20) is None


class TestMaxDrawdown:
    def test_monotonic_rise_has_no_drawdown(self):
        assert tech.max_drawdown([float(i) for i in range(1, 61)], 60) == 0.0

    def test_halving_gives_minus_50_percent(self):
        closes = [100.0] * 30 + [50.0] * 30
        assert tech.max_drawdown(closes, 60) == pytest.approx(-50.0)

    def test_returns_none_when_sample_too_short(self):
        assert tech.max_drawdown([1.0] * 10, 60) is None


class TestATR:
    def test_constant_range_equals_that_range(self):
        closes = [10.0] * 20
        highs = [10.5] * 20
        lows = [9.5] * 20
        assert tech.atr(make_bars(closes, highs, lows), 14) == pytest.approx(1.0)

    def test_returns_none_when_sample_too_short(self):
        assert tech.atr(make_bars([10.0] * 5), 14) is None


class TestVolumeTrend:
    def test_flat_volume_is_one(self):
        assert tech.volume_trend([100.0] * 20) == pytest.approx(1.0)

    def test_surge_is_above_one(self):
        assert tech.volume_trend([100.0] * 15 + [300.0] * 5) > 1

    def test_returns_none_when_sample_too_short(self):
        assert tech.volume_trend([100.0] * 5) is None


class TestComputeTechnicals:
    def test_every_point_carries_as_of_and_source(self):
        bars = make_bars([100 + i * 0.5 for i in range(250)])
        points = tech.compute_technicals(bars).points
        assert points
        for point in points.values():
            assert point.source
            assert point.as_of == bars.as_of

    def test_short_history_omits_long_window_indicators(self):
        points = tech.compute_technicals(make_bars([100.0] * 30)).points
        assert "technical_sma_20" in points
        assert "technical_sma_200" not in points
        assert "risk_max_drawdown_60d" not in points

    def test_no_fabricated_values_on_minimal_history(self):
        """样本极短时宁可一项不出，也不得给默认值。"""
        points = tech.compute_technicals(make_bars([100.0, 101.0])).points
        assert points == {}

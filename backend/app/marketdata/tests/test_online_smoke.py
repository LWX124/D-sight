"""真网冒烟：确认 akshare 上游接口仍返回本层依赖的字段。

默认不跑（pyproject 里 addopts = -m 'not online'）。本地验收：
    pytest app/marketdata -m online
失败通常意味着上游字段变更或出口被封，需重跑
`scripts/spikes/probe_akshare.py` 与 `record_marketdata_fixtures.py`。
"""

from datetime import date, timedelta

import pytest

from app.marketdata import (
    compute_technicals,
    get_daily_bars,
    get_events,
    get_financials,
    get_profile,
    get_valuation,
)

pytestmark = pytest.mark.online

SYMBOL = "600519"


def test_daily_bars_are_fresh():
    bars = get_daily_bars(SYMBOL, lookback=250)
    assert len(bars) >= 200
    assert bars.as_of >= date.today() - timedelta(days=10), "最新日线超过 10 天未更新"
    assert bars.bars[-1].close > 0


def test_technicals_cover_full_indicator_set():
    points = compute_technicals(get_daily_bars(SYMBOL, lookback=300)).points
    for key in ("technical_sma_20", "technical_sma_200", "technical_rsi_14",
                "technical_macd", "risk_max_drawdown_60d", "risk_atr_14"):
        assert key in points, key


def test_valuation_has_multiples_and_percentiles():
    points = get_valuation(SYMBOL).points
    assert points["valuation_pe"].value > 0
    assert points["valuation_pb"].value > 0
    assert 0 <= points["valuation_pe_percentile"].value <= 100


def test_financials_report_period_is_recent():
    points = get_financials(SYMBOL).points
    period = points["fundamentals_revenue"].period
    assert int(period[:4]) >= date.today().year - 1, "最新报告期落后超过一年"


def test_profile_resolves_the_right_company():
    points = get_profile(SYMBOL).points
    assert "茅台" in points["identity_name"].value


def test_events_carry_their_own_period():
    """分红字段各有自己的报告期：方案披露与实施除权不是同一天，
    共用一个 as_of 会让除权日看起来发生在披露之前。"""
    points = get_events(SYMBOL).points
    assert points["events_dividend_per_10_shares"].value > 0
    assert points["events_ex_dividend_date"].as_of >= points["events_earnings"].as_of

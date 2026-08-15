"""取数模块离线测试：用录制的真实返回驱动解析逻辑，不触网。"""

from datetime import date

import pytest

from app.marketdata import events, financials, profile, quotes, valuation
from app.marketdata.errors import MarketNotSupported, SymbolNotFound
from app.marketdata.symbols import exchange_of, normalize_cn_code, to_sina_symbol


class TestSymbols:
    @pytest.mark.parametrize(
        "raw,expected",
        [("600519", "600519"), ("sh600519", "600519"), ("600519.SH", "600519"), ("  000001 ", "000001")],
    )
    def test_normalize_extracts_six_digits(self, raw, expected):
        assert normalize_cn_code(raw) == expected

    @pytest.mark.parametrize(
        "code,exchange",
        [("600519", "sh"), ("900901", "sh"), ("000001", "sz"), ("300750", "sz"),
         ("920000", "bj"), ("430047", "bj"), ("830799", "bj")],
    )
    def test_exchange_mapping(self, code, exchange):
        """900xxx 是沪市 B 股，不能被 9→bj 的规则误判。"""
        assert exchange_of(code) == exchange

    def test_to_sina_symbol(self):
        assert to_sina_symbol("600519") == "sh600519"

    def test_rejects_non_stock_input(self):
        with pytest.raises(SymbolNotFound):
            normalize_cn_code("茅台")


class TestQuotes:
    def test_parses_bars_with_provenance(self, fake_fetch_df):
        fake_fetch_df(quotes, "stock_zh_a_daily", "daily_600519")
        bars = quotes.get_daily_bars("600519", lookback=100)

        assert len(bars) == 100
        assert bars.source.startswith("akshare:")
        assert isinstance(bars.as_of, date)
        assert all(b.close > 0 for b in bars.bars)

    def test_bars_are_sorted_ascending(self, fake_fetch_df):
        fake_fetch_df(quotes, "stock_zh_a_daily", "daily_600519")
        bars = quotes.get_daily_bars("600519", lookback=50)
        assert [b.date for b in bars.bars] == sorted(b.date for b in bars.bars)

    def test_latest_quote_marks_close_not_realtime(self, fake_fetch_df):
        fake_fetch_df(quotes, "stock_zh_a_daily", "daily_600519")
        points = quotes.get_quote("600519")

        assert points["quote_price"].value > 0
        assert points["quote_price"].as_of == points["quote_volume"].as_of
        assert any("非实时" in w for w in points["quote_price"].warnings)

    def test_non_cn_market_rejected(self):
        with pytest.raises(MarketNotSupported):
            quotes.get_daily_bars("AAPL", market="US")


class TestValuation:
    def test_extracts_core_multiples(self, fake_fetch_df):
        fake_fetch_df(valuation, "stock_value_em", "value_em_600519")
        points = valuation.get_valuation("600519").points

        for key in ("valuation_pe", "valuation_pb", "valuation_ps", "quote_market_cap"):
            assert key in points, key
            assert points[key].source
            assert points[key].as_of

    def test_percentile_is_within_range_and_labelled(self, fake_fetch_df):
        fake_fetch_df(valuation, "stock_value_em", "value_em_600519")
        points = valuation.get_valuation("600519").points

        pct = points["valuation_pe_percentile"]
        assert 0 <= pct.value <= 100
        assert pct.unit == "%"
        assert pct.period  # 分位必须声明样本区间

    def test_percentile_ignores_non_positive_samples(self):
        import pandas as pd
        series = pd.Series([-5.0, 10.0, 20.0, 30.0] * 20)
        assert valuation._percentile(series, 20.0) == pytest.approx(66.67, abs=0.1)

    def test_percentile_requires_minimum_sample(self):
        import pandas as pd
        assert valuation._percentile(pd.Series([10.0] * 10), 10.0) is None

    def test_non_cn_market_rejected(self):
        with pytest.raises(MarketNotSupported):
            valuation.get_valuation("AAPL", market="US")


class TestFinancials:
    def test_extracts_latest_period(self, fake_fetch_df):
        fake_fetch_df(financials, "stock_financial_abstract", "financial_abstract_600519")
        points = financials.get_financials("600519").points

        for key in ("fundamentals_revenue", "fundamentals_net_income", "fundamentals_roe",
                    "fundamentals_debt_ratio", "fundamentals_operating_cash_flow"):
            assert key in points, key
            assert points[key].period  # 财务数据必须带报告期

    def test_yoy_compares_same_quarter_last_year(self, fake_fetch_df):
        fake_fetch_df(financials, "stock_financial_abstract", "financial_abstract_600519")
        points = financials.get_financials("600519").points

        current = points["fundamentals_revenue_current"].period
        previous = points["fundamentals_revenue_previous"].period
        assert int(current[:4]) - int(previous[:4]) == 1
        assert current[4:] == previous[4:], "A 股季报是累计口径，同比只能比去年同期"

    def test_gross_profit_is_flagged_as_derived(self, fake_fetch_df):
        fake_fetch_df(financials, "stock_financial_abstract", "financial_abstract_600519")
        points = financials.get_financials("600519").points

        gross = points["fundamentals_gross_profit"]
        assert gross.warnings, "推导值必须标注来源"
        assert gross.value == pytest.approx(
            points["fundamentals_revenue"].value - points["fundamentals_cost_of_revenue"].value
        )

    def test_period_helpers(self):
        assert financials._same_period_last_year("20260331") == "20250331"
        assert financials._period_to_date("20251231") == date(2025, 12, 31)

    def test_non_cn_market_rejected(self):
        with pytest.raises(MarketNotSupported):
            financials.get_financials("AAPL", market="US")


class TestProfile:
    def test_extracts_identity(self, fake_fetch_df):
        fake_fetch_df(profile, "stock_profile_cninfo", "profile_600519")
        points = profile.get_profile("600519").points

        assert "茅台" in points["identity_name"].value
        assert points["identity_industry"].value
        assert points["identity_listing_date"].value.startswith("20")

    def test_sector_reuse_is_disclosed(self, fake_fetch_df):
        fake_fetch_df(profile, "stock_profile_cninfo", "profile_600519")
        points = profile.get_profile("600519").points

        assert points["identity_sector"].value == points["identity_industry"].value
        assert points["identity_sector"].warnings

    def test_as_of_is_fetch_date_not_faked(self, fake_fetch_df):
        fake_fetch_df(profile, "stock_profile_cninfo", "profile_600519")
        points = profile.get_profile("600519").points
        assert points["identity_name"].as_of == date.today()

    def test_non_cn_market_rejected(self):
        with pytest.raises(MarketNotSupported):
            profile.get_profile("AAPL", market="US")


class TestEvents:
    def test_extracts_latest_dividend_plan(self, fake_fetch_df):
        fake_fetch_df(events, "stock_fhps_detail_em", "fhps_600519")
        points = events.get_events("600519").points

        assert "events_dividends" in points
        assert points["events_dividends"].period  # 事件必须落在报告期上
        assert points["events_dividends"].source.startswith("akshare:")

    def test_takes_the_most_recent_period(self, fake_fetch_df):
        fake_fetch_df(events, "stock_fhps_detail_em", "fhps_600519")
        points = events.get_events("600519").points

        import pandas as pd
        from app.marketdata.tests.conftest import load_fixture
        periods = pd.to_datetime(load_fixture("fhps_600519")["报告期"], errors="coerce").dropna()
        assert points["events_dividends"].period == periods.max().strftime("%Y%m%d")

    def test_unimplemented_plan_is_flagged(self, fake_fetch_df):
        """预案未实施时金额可能变动，必须随值暴露，不能只给数字。"""
        fake_fetch_df(events, "stock_fhps_detail_em", "fhps_600519")
        points = events.get_events("600519").points

        progress = points.get("events_plan_progress")
        if progress is not None and progress.value != "实施分配":
            assert points["events_dividends"].warnings

    def test_concrete_amount_comes_from_latest_priced_plan(self, fake_fetch_df):
        """最新一行可能是无金额的预披露；金额必须回退到最近一次有确切金额的方案。"""
        fake_fetch_df(events, "stock_fhps_detail_em", "fhps_600519")
        points = events.get_events("600519").points

        amount = points["events_dividend_per_10_shares"]
        assert amount.value > 0
        # 金额那条的报告期可以早于最新方案的报告期，二者各自独立标注
        assert amount.period <= points["events_dividends"].period

    def test_as_of_is_announcement_date(self, fake_fetch_df):
        fake_fetch_df(events, "stock_fhps_detail_em", "fhps_600519")
        points = events.get_events("600519").points

        for item in points.values():
            assert isinstance(item.as_of, date)

    def test_non_cn_market_rejected(self):
        with pytest.raises(MarketNotSupported):
            events.get_events("AAPL", market="US")


class TestContracts:
    """跨模块的硬约束：任何取值都必须能追溯。"""

    def test_datapoint_rejects_missing_source(self):
        from app.marketdata.schemas import DataPoint
        with pytest.raises(ValueError):
            DataPoint(key="x", value=1.0, as_of=date.today(), source="")

    def test_datapoint_rejects_missing_as_of(self):
        from app.marketdata.schemas import DataPoint
        with pytest.raises(ValueError):
            DataPoint(key="x", value=1.0, as_of=None, source="akshare")

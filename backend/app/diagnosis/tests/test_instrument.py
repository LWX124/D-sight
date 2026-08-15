"""
Unit Tests for Instrument Registry

Tests A-share and US stock symbol normalization.
"""

from ...diagnosis.instrument import normalize_symbol
from ...diagnosis.evidence.schemas import Market


class TestInstrumentRegistry:
    """Test cases for instrument normalization."""

    def test_cn_sh_code(self):
        """Test Shanghai stock code normalization."""
        result = normalize_symbol('600519', 'CN')
        assert result.instrument is not None
        assert result.instrument.market == Market.CN
        assert result.instrument.canonical_symbol == '600519.SH'
        assert result.instrument.exchange == 'SSE'

    def test_cn_sz_code(self):
        """Test Shenzhen stock code normalization."""
        result = normalize_symbol('000001', 'CN')
        assert result.instrument is not None
        assert result.instrument.market == Market.CN
        assert result.instrument.canonical_symbol == '000001.SZ'
        assert result.instrument.exchange == 'SZSE'

    def test_cn_bj_code(self):
        """Test Beijing stock code normalization."""
        result = normalize_symbol('430047', 'CN')
        assert result.instrument is not None
        assert result.instrument.market == Market.CN
        assert result.instrument.canonical_symbol == '430047.BJ'
        assert result.instrument.exchange == 'BSE'

    def test_cn_with_suffix(self):
        """Test CN code with exchange suffix."""
        result = normalize_symbol('600519.SH', 'CN')
        assert result.instrument is not None
        assert result.instrument.canonical_symbol == '600519.SH'

    def test_us_ticker(self):
        """Test US ticker normalization."""
        result = normalize_symbol('AAPL', 'US')
        assert result.instrument is not None
        assert result.instrument.market == Market.US
        assert result.instrument.canonical_symbol == 'AAPL'
        assert result.instrument.exchange is None
        assert result.instrument.currency == 'USD'

    def test_us_ticker_lowercase(self):
        """Test US ticker with lowercase."""
        result = normalize_symbol('aapl', 'US')
        assert result.instrument is not None
        assert result.instrument.canonical_symbol == 'AAPL'

    def test_unknown_input(self):
        """Test unknown input returns error."""
        result = normalize_symbol('INVALID', 'CN')
        assert result.instrument is None
        assert result.error is not None

    def test_auto_market_detection(self):
        """Test automatic market detection."""
        # Should detect as CN
        result_cn = normalize_symbol('600519')
        assert result_cn.instrument is not None
        assert result_cn.instrument.market == Market.CN

        # Should detect as US
        result_us = normalize_symbol('AAPL')
        assert result_us.instrument is not None
        assert result_us.instrument.market == Market.US

    def test_instrument_fields(self):
        """Test that instrument has all required fields."""
        result = normalize_symbol('600519', 'CN')
        assert result.instrument is not None

        instrument = result.instrument
        assert instrument.market is not None
        assert instrument.canonical_symbol is not None
        assert instrument.exchange is not None
        assert instrument.currency is not None
        assert instrument.timezone is not None
        assert instrument.original_input is not None
        assert instrument.normalization_method is not None

    def test_instrument_serialization(self):
        """Test instrument serialization to dict."""
        result = normalize_symbol('600519', 'CN')
        assert result.instrument is not None

        data = result.instrument.to_dict()
        assert 'market' in data
        assert 'canonical_symbol' in data
        assert 'exchange' in data
        assert data['market'] == 'CN'
        assert data['canonical_symbol'] == '600519.SH'


class TestEdgeCases:
    """Test edge cases for instrument normalization."""

    def test_empty_input(self):
        """Test empty input."""
        result = normalize_symbol('', 'CN')
        assert result.instrument is None
        assert result.error is not None

    def test_whitespace_input(self):
        """Test whitespace input."""
        result = normalize_symbol('  600519  ', 'CN')
        assert result.instrument is not None
        assert result.instrument.canonical_symbol == '600519.SH'
        assert result.instrument.original_input == '  600519  '

    def test_lowercase_raw_input_is_preserved(self):
        result = normalize_symbol('aapl', 'US')

        assert result.instrument is not None
        assert result.instrument.original_input == 'aapl'
        assert result.instrument.normalization_method == 'ticker_pattern'

    def test_special_characters(self):
        """Test input with special characters."""
        result = normalize_symbol('600519!', 'CN')
        # Special characters are not stripped by default
        # This test documents the current behavior
        assert result.instrument is None
        assert result.error is not None

    def test_long_input(self):
        """Test very long input."""
        long_input = 'A' * 100
        result = normalize_symbol(long_input, 'US')
        assert result.instrument is None
        assert result.error is not None

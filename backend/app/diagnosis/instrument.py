"""
Instrument Registry for Stock Diagnosis

Handles canonical symbol normalization for A-share and US stocks.
Supports multiple input formats and handles name ambiguity.
"""

import re
from dataclasses import dataclass
from typing import Optional
from .evidence.schemas import Instrument, Market


@dataclass
class NormalizationResult:
    """Result of instrument normalization."""
    instrument: Optional[Instrument]
    candidates: list[Instrument]
    ambiguity: bool
    error: Optional[str] = None


class InstrumentRegistry:
    """Registry for normalizing stock symbols."""

    # A-share code patterns
    CN_SH_PATTERN = re.compile(r'^(6\d{5}|688\d{4}|689\d{4})$')  # Shanghai
    CN_SZ_PATTERN = re.compile(r'^(0\d{5}|2\d{5}|3\d{5})$')  # Shenzhen
    CN_BJ_PATTERN = re.compile(r'^(4\d{5}|8\d{5}|92\d{4})$')  # Beijing

    # US ticker patterns
    US_TICKER_PATTERN = re.compile(r'^[A-Z]{1,5}$')
    US_CUSIP_PATTERN = re.compile(r'^\d{9}$')
    US_ISIN_PATTERN = re.compile(r'^[A-Z]{2}\d{10}$')

    def normalize(self, input_str: str, market_hint: Optional[str] = None) -> NormalizationResult:
        """
        Normalize a stock symbol to canonical form.

        Args:
            input_str: Raw input (code, name, or ticker)
            market_hint: Optional market hint ('CN', 'US', etc.)

        Returns:
            NormalizationResult with normalized instrument or candidates
        """
        original_input = input_str
        normalized_input = input_str.strip()

        # Try market-specific normalization
        if market_hint == 'CN' or not market_hint:
            result = self._normalize_cn(normalized_input, original_input)
            if result.instrument or result.candidates:
                return result

        if market_hint == 'US' or not market_hint:
            result = self._normalize_us(normalized_input, original_input)
            if result.instrument or result.candidates:
                return result

        # If no market specified and no match, try both
        if not market_hint:
            cn_result = self._normalize_cn(normalized_input, original_input)
            us_result = self._normalize_us(normalized_input, original_input)

            if cn_result.instrument and us_result.instrument:
                # Ambiguous - return both candidates
                return NormalizationResult(
                    instrument=None,
                    candidates=[cn_result.instrument, us_result.instrument],
                    ambiguity=True
                )
            elif cn_result.instrument:
                return cn_result
            elif us_result.instrument:
                return us_result

        return NormalizationResult(
            instrument=None,
            candidates=[],
            ambiguity=False,
            error=f"Could not normalize '{normalized_input}' for market {market_hint}"
        )

    def _normalize_cn(self, input_str: str, original_input: str) -> NormalizationResult:
        """Normalize A-share symbols."""
        # Remove common prefixes
        code = input_str.upper().replace('.SH', '').replace('.SZ', '').replace('.BJ', '')

        # Check if it's a 6-digit code
        if re.match(r'^\d{6}$', code):
            return self._normalize_cn_code(code, original_input)

        # Check if it's a name (Chinese characters)
        if re.match(r'^[一-龥]+$', input_str):
            return self._normalize_cn_name(input_str)

        return NormalizationResult(
            instrument=None,
            candidates=[],
            ambiguity=False,
            error=f"Could not normalize CN input: {input_str}"
        )

    def _normalize_cn_code(self, code: str, original_input: str) -> NormalizationResult:
        """Normalize a 6-digit A-share code."""
        code = code.zfill(6)

        # Determine exchange based on code prefix
        if self.CN_SH_PATTERN.match(code):
            exchange = 'SSE'
            symbol = f"{code}.SH"
            timezone = 'Asia/Shanghai'
        elif self.CN_SZ_PATTERN.match(code):
            exchange = 'SZSE'
            symbol = f"{code}.SZ"
            timezone = 'Asia/Shanghai'
        elif self.CN_BJ_PATTERN.match(code):
            exchange = 'BSE'
            symbol = f"{code}.BJ"
            timezone = 'Asia/Shanghai'
        else:
            return NormalizationResult(
                instrument=None,
                candidates=[],
                ambiguity=False,
                error=f"Unknown CN code pattern: {code}"
            )

        instrument = Instrument(
            market=Market.CN,
            canonical_symbol=symbol,
            exchange=exchange,
            currency='CNY',
            timezone=timezone,
            original_input=original_input,
            normalization_method='code_pattern',
        )

        return NormalizationResult(
            instrument=instrument,
            candidates=[],
            ambiguity=False
        )

    def _normalize_cn_name(self, name: str) -> NormalizationResult:
        """Normalize a Chinese stock name."""
        # This would typically query a database or API
        # For now, return placeholder
        return NormalizationResult(
            instrument=None,
            candidates=[],
            ambiguity=False,
            error=f"Name-based lookup not implemented: {name}"
        )

    def _normalize_us(self, input_str: str, original_input: str) -> NormalizationResult:
        """Normalize US stock symbols."""
        input_str = input_str.upper()

        # Check if it's a ticker
        if self.US_TICKER_PATTERN.match(input_str):
            return self._normalize_us_ticker(input_str, original_input)

        # Check if it's a CUSIP
        if self.US_CUSIP_PATTERN.match(input_str):
            return self._normalize_us_cusip(input_str)

        # Check if it's an ISIN
        if self.US_ISIN_PATTERN.match(input_str):
            return self._normalize_us_isin(input_str)

        return NormalizationResult(
            instrument=None,
            candidates=[],
            ambiguity=False,
            error=f"Could not normalize US input: {input_str}"
        )

    def _normalize_us_ticker(self, ticker: str, original_input: str) -> NormalizationResult:
        """Normalize a US ticker symbol."""
        instrument = Instrument(
            market=Market.US,
            canonical_symbol=ticker,
            exchange=None,
            currency='USD',
            timezone='America/New_York',
            original_input=original_input,
            normalization_method='ticker_pattern',
        )

        return NormalizationResult(
            instrument=instrument,
            candidates=[],
            ambiguity=False
        )

    def _normalize_us_cusip(self, cusip: str) -> NormalizationResult:
        """Normalize a US CUSIP."""
        # Would lookup CUSIP to ticker mapping
        return NormalizationResult(
            instrument=None,
            candidates=[],
            ambiguity=False,
            error=f"CUSIP lookup not implemented: {cusip}"
        )

    def _normalize_us_isin(self, isin: str) -> NormalizationResult:
        """Normalize a US ISIN."""
        # Would lookup ISIN to ticker mapping
        return NormalizationResult(
            instrument=None,
            candidates=[],
            ambiguity=False,
            error=f"ISIN lookup not implemented: {isin}"
        )


# Global registry instance
_registry: Optional[InstrumentRegistry] = None


def get_registry() -> InstrumentRegistry:
    """Get the global instrument registry."""
    global _registry
    if _registry is None:
        _registry = InstrumentRegistry()
    return _registry


def normalize_symbol(input_str: str, market_hint: Optional[str] = None) -> NormalizationResult:
    """
    Normalize a stock symbol to canonical form.

    Args:
        input_str: Raw input (code, name, or ticker)
        market_hint: Optional market hint ('CN', 'US', etc.)

    Returns:
        NormalizationResult with normalized instrument or candidates
    """
    return get_registry().normalize(input_str, market_hint)

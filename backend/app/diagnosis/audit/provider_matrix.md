# A/US Stock Data Provider Matrix

## Status: Phase 0 Audit

## A-Share Providers

### 1. AkShare (akshare)
- **Type**: Free, open-source
- **License**: MIT
- **Fields**: Real-time quotes, historical bars, financials, dividends, shareholder data
- **Freshness**: Real-time for quotes, T+1 for financials
- **Limitations**: Rate limits, some APIs may be blocked in certain regions
- **Redistribution**: Allowed with attribution
- **Commercial Use**: Allowed
- **Current Usage**: Used in `backend/app/agent/tools/stock.py`

### 2. Pandadata API
- **Type**: Token-based
- **License**: Custom (requires skill-pandadata-api)
- **Fields**: Comprehensive A-share data including fundamentals, shareholder structure, event risks
- **Freshness**: Real-time to daily depending on data type
- **Limitations**: Requires API key, rate limits
- **Redistribution**: Unknown (skill not materialized)
- **Commercial Use**: Unknown
- **Current Usage**: Referenced by 8 stock Skills (all unavailable)

### 3. Tushare
- **Type**: Token-based (free tier available)
- **License**: Custom
- **Fields**: Comprehensive A-share data
- **Freshness**: Real-time to daily
- **Limitations**: Rate limits, some data requires paid subscription
- **Redistribution**: Not allowed without permission
- **Commercial Use**: Requires paid subscription
- **Current Usage**: Not integrated

## US Stock Providers

### 1. Yahoo Finance (yfinance)
- **Type**: Free, unofficial API
- **License**: No official license (unofficial wrapper)
- **Fields**: Real-time quotes, historical bars, financials, dividends
- **Freshness**: Real-time for quotes, delayed for some data
- **Limitations**: Unofficial, may break, rate limits
- **Redistribution**: Uncertain
- **Commercial Use**: Uncertain
- **Current Usage**: Not integrated

### 2. Alpha Vantage
- **Type**: Free tier available
- **License**: Free for non-commercial, paid for commercial
- **Fields**: Real-time and historical quotes, technicals, fundamentals
- **Freshness**: Real-time to delayed
- **Limitations**: 5 calls/minute free tier, 500 calls/day
- **Redistribution**: Allowed with attribution
- **Commercial Use**: Requires paid subscription
- **Current Usage**: Not integrated

### 3. Financial Modeling Prep (FMP)
- **Type**: Free tier available
- **License**: Free for non-commercial
- **Fields**: Comprehensive US stock data
- **Freshness**: Real-time
- **Limitations**: 250 calls/day free tier
- **Redistribution**: Allowed
- **Commercial Use**: Requires paid subscription
- **Current Usage**: Not integrated

## Provider Chain Strategy

### A-Share Fallback Chain
1. **Primary**: AkShare (free, reliable)
2. **Fallback**: Tushare (if AkShare fails)
3. **Premium**: Pandadata API (if available and licensed)

### US Stock Fallback Chain
1. **Primary**: Yahoo Finance (free, widely available)
2. **Fallback**: Alpha Vantage (if Yahoo fails)
3. **Premium**: FMP (if available and licensed)

## License Compliance Notes

### AkShare
- MIT License: allows use, modification, distribution
- Requires attribution in documentation
- Commercial use allowed

### Yahoo Finance
- No official license (unofficial API)
- Terms of Service may restrict commercial use
- Risk of API changes or blocking

### Alpha Vantage
- Free tier: non-commercial use only
- Paid tier: commercial use allowed
- Requires attribution

## Phase 0 Actions Required

1. **Verify AkShare license compliance** for production use
2. **Research Pandadata API** licensing and availability
3. **Evaluate Yahoo Finance** reliability and legal status
4. **Test provider fallback chains** with real data
5. **Document rate limits** and caching requirements
6. **Create provider health monitoring** endpoints

## Recommendations

1. **Start with AkShare** for A-share (proven, MIT licensed)
2. **Use Yahoo Finance** for US stocks (widely available)
3. **Avoid Pandadata** until skill dependencies are resolved
4. **Implement caching** to reduce API calls
5. **Monitor provider health** and fallback automatically

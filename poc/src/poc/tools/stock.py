from langchain_core.tools import tool


@tool
def stock_quote(symbol: str) -> str:
    """查询 A 股公司概况与实时行情。symbol 为 6 位代码，如 600519。"""
    import akshare as ak

    df = ak.stock_individual_info_em(symbol=symbol)
    return df.to_string(index=False)


@tool
def stock_financials(symbol: str) -> str:
    """查询 A 股主要财务指标（近年）。symbol 为 6 位代码，如 600519。"""
    import akshare as ak

    df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2020")
    return df.tail(12).to_string(index=False)

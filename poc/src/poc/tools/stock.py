import pandas as pd
from langchain_core.tools import tool

from poc.tools.safe import tool_guard


def _sina_symbol(symbol: str) -> str:
    """把 6 位 A 股代码映射为新浪接口所需的带市场前缀代码（sh/sz/bj）。"""
    code = symbol.strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if code.startswith(prefix):
            return code
    code = code.zfill(6)
    # 北交所：92 开头（及历史 4/8 开头）→ bj；必须在 9→sh 之前判断，
    # 否则 900xxx 沪市 B 股会被误判。
    if code.startswith("92") or code[0] in ("4", "8"):
        return f"bj{code}"
    if code[0] in ("6", "9"):
        return f"sh{code}"
    if code[0] in ("0", "2", "3"):
        return f"sz{code}"
    return f"sh{code}"


@tool
@tool_guard
def stock_quote(symbol: str) -> str:
    """查询 A 股近期行情（前复权日线，最后一行为最新交易日）。symbol 为 6 位代码，如 600519。

    数据源：新浪财经 stock_zh_a_daily（本环境东财 API 出口被封，故改用新浪源）。
    """
    import akshare as ak

    sina = _sina_symbol(symbol)
    df = ak.stock_zh_a_daily(symbol=sina, adjust="qfq")
    if df is None or df.empty:
        return f"错误：未查到 {symbol} 的行情数据，请核对代码或告知用户。"
    recent = df.tail(15)
    latest = df.iloc[-1]
    header = (
        f"{symbol}（{sina}）近 15 个交易日前复权行情，"
        f"最新交易日 {latest['date']} 收盘 {latest['close']}\n"
    )
    return header + recent.to_string(index=False)


@tool
@tool_guard
def stock_financials(symbol: str) -> str:
    """查询 A 股主要财务指标（近 8 个报告期的常用指标）。symbol 为 6 位代码，如 600519。

    数据源：新浪财经 stock_financial_abstract（本环境东财 API 出口被封，故改用新浪源）。
    指标含营业总收入、归母净利润、扣非净利润、ROE、毛利率、销售净利率、资产负债率、每股收益等。
    """
    import akshare as ak

    df = ak.stock_financial_abstract(symbol=symbol.strip().zfill(6))
    if df is None or df.empty:
        return f"错误：未查到 {symbol} 的财务数据，请核对代码或告知用户。"
    date_cols = [c for c in df.columns if c not in ("选项", "指标")]
    recent_dates = date_cols[:8]
    core = df[df["选项"] == "常用指标"] if "选项" in df.columns else df
    view = core[["指标", *recent_dates]].copy()
    with pd.option_context(
        "display.float_format", lambda x: f"{x:,.2f}", "display.max_colwidth", 24
    ):
        table = view.to_string(index=False)
    return f"{symbol} 近 8 期常用财务指标（金额单位：元；比率单位：%）：\n{table}"

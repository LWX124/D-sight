"""A 股数据接口 spike：验证字段覆盖率。

测试标的：
- 600519.SH 贵州茅台（大盘消费）
- 000001.SZ 平安银行（金融）
- 300750.SZ 宁德时代（科创）

验证的 MarketData 字段：
- prices: 近90日日线（date/open/high/low/close/volume）
- financial_metrics: PE/PB/ROE/负债率
- income: 营收/净利润/毛利率（近4~8期）
- balance: 总资产/总负债/净资产/现金（近4期）
- cashflow: 经营/投资/筹资现金流（近4期）
- company_info: 公司名/交易所/行业
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    import akshare as ak
except ImportError:
    print("ERROR: akshare 未安装，运行: pip install akshare")
    sys.exit(1)

TICKERS = [
    ("600519", "SH", "贵州茅台"),
    ("000001", "SZ", "平安银行"),
    ("300750", "SZ", "宁德时代"),
]

results = {}

for code, exchange, name in TICKERS:
    print(f"\n===== {name} ({code}.{exchange}) =====")
    r = {"ticker": f"{code}.{exchange}", "name": name, "fields": {}}

    # 1. 日线价格
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(date.today() - timedelta(days=90)).strftime("%Y%m%d"),
            end_date=date.today().strftime("%Y%m%d"),
            adjust="qfq",
        )
        r["fields"]["prices"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns),
            "sample": df.tail(2).to_dict("records"),
        }
        print(f"  prices: {len(df)} 行, 列={list(df.columns)}")
    except Exception as e:
        r["fields"]["prices"] = {"ok": False, "error": str(e)}
        print(f"  prices: ERROR {e}")

    # 2. 财务比率
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2022")
        r["fields"]["financial_metrics"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:20],  # 前20列
        }
        print(f"  financial_metrics: {len(df)} 行, {len(df.columns)} 列")
    except Exception as e:
        r["fields"]["financial_metrics"] = {"ok": False, "error": str(e)}
        print(f"  financial_metrics: ERROR {e}")

    # 3. 利润表
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="利润表")
        r["fields"]["income"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:10],
        }
        print(f"  income: {len(df)} 行")
    except Exception as e:
        r["fields"]["income"] = {"ok": False, "error": str(e)}
        print(f"  income: ERROR {e}")

    # 4. 资产负债表
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="资产负债表")
        r["fields"]["balance"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:10],
        }
        print(f"  balance: {len(df)} 行")
    except Exception as e:
        r["fields"]["balance"] = {"ok": False, "error": str(e)}
        print(f"  balance: ERROR {e}")

    # 5. 现金流量表
    try:
        df = ak.stock_financial_report_sina(stock=code, symbol="现金流量表")
        r["fields"]["cashflow"] = {
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns)[:10],
        }
        print(f"  cashflow: {len(df)} 行")
    except Exception as e:
        r["fields"]["cashflow"] = {"ok": False, "error": str(e)}
        print(f"  cashflow: ERROR {e}")

    # 6. 公司信息
    try:
        df = ak.stock_individual_info_em(symbol=code)
        r["fields"]["company_info"] = {
            "ok": True,
            "data": dict(zip(df.iloc[:, 0], df.iloc[:, 1])),
        }
        print(f"  company_info: OK")
    except Exception as e:
        r["fields"]["company_info"] = {"ok": False, "error": str(e)}
        print(f"  company_info: ERROR {e}")

    results[code] = r

out = Path("scripts/spikes/spike_a_share_raw.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
print(f"\n原始结果已写入 {out}")

# 覆盖率统计
print("\n===== 字段覆盖率摘要 =====")
fields = ["prices", "financial_metrics", "income", "balance", "cashflow", "company_info"]
for f in fields:
    ok_count = sum(1 for r in results.values() if r["fields"].get(f, {}).get("ok"))
    print(f"  {f}: {ok_count}/{len(TICKERS)} 成功")

"""探测 akshare 各接口在本环境的可用性。

背景：代码注释称"东财 API 出口被封"，需重新确认；估值 PE/PB 走哪个源是关键未知。
用法: PYTHONPATH=. .venv/bin/python scripts/spikes/probe_akshare.py
"""
import time

import akshare as ak

from app.core.akshare_runtime import call_akshare

SYMBOL = "600519"
SINA = "sh600519"


def probe(name: str, fn, *args, **kwargs):
    t0 = time.time()
    try:
        df = call_akshare(fn, *args, **kwargs)
        dt = time.time() - t0
        if df is None:
            print(f"[NONE ] {name}  ({dt:.1f}s) -> None")
            return None
        shape = getattr(df, "shape", None)
        cols = list(getattr(df, "columns", []))[:12]
        print(f"[OK   ] {name}  ({dt:.1f}s) shape={shape}")
        print(f"         cols={cols}")
        try:
            print("         tail:\n" + df.tail(2).to_string()[:600])
        except Exception:
            print(f"         val: {str(df)[:300]}")
        return df
    except Exception as e:
        dt = time.time() - t0
        print(f"[FAIL ] {name}  ({dt:.1f}s) {type(e).__name__}: {str(e)[:160]}")
        return None


print("=" * 70)
print("3. 估值 PE/PB —— 关键未知")
print("=" * 70)
probe("stock_value_em(东财个股估值)", ak.stock_value_em, symbol=SYMBOL)
probe("stock_zh_valuation_baidu(百度PE-TTM近一年)", ak.stock_zh_valuation_baidu,
      symbol=SYMBOL, indicator="市盈率(TTM)", period="近一年")
probe("stock_zh_valuation_baidu(百度PB近五年)", ak.stock_zh_valuation_baidu,
      symbol=SYMBOL, indicator="市净率", period="近五年")
probe("stock_zh_valuation_baidu(百度总市值)", ak.stock_zh_valuation_baidu,
      symbol=SYMBOL, indicator="总市值", period="近一年")
probe("stock_financial_analysis_indicator_em(东财)",
      ak.stock_financial_analysis_indicator_em, symbol=SYMBOL, indicator="按报告期")

print("=" * 70)
print("4. 个股基本信息")
print("=" * 70)
probe("stock_individual_info_em(东财)", ak.stock_individual_info_em, symbol=SYMBOL)

print("=" * 70)
print("5. 全市场快照（Phase 2 策略筛选预探）")
print("=" * 70)
probe("stock_zh_a_spot_em(东财全市场)", ak.stock_zh_a_spot_em)

print("=" * 70)
print("6. 行业板块（Phase 1 板块热度预探）")
print("=" * 70)
probe("stock_board_industry_name_em(东财行业板块)", ak.stock_board_industry_name_em)
probe("stock_board_industry_cons_em(板块成分-白酒)",
      ak.stock_board_industry_cons_em, symbol="酿酒行业")

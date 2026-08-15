"""探测二：东财 push2.* 域被代理拦截后，个股基本信息/全市场快照/行业板块的替代源。"""
import time

import akshare as ak

from app.core.akshare_runtime import call_akshare

SYMBOL = "600519"


def probe(name: str, fn, *args, **kwargs):
    t0 = time.time()
    try:
        df = call_akshare(fn, *args, **kwargs)
        dt = time.time() - t0
        if df is None:
            print(f"[NONE ] {name}  ({dt:.1f}s) -> None")
            return None
        print(f"[OK   ] {name}  ({dt:.1f}s) shape={getattr(df, 'shape', None)}")
        print(f"         cols={list(getattr(df, 'columns', []))[:14]}")
        try:
            print("         head:\n" + df.head(3).to_string()[:700])
        except Exception:
            print(f"         val: {str(df)[:300]}")
        return df
    except Exception as e:
        dt = time.time() - t0
        print(f"[FAIL ] {name}  ({dt:.1f}s) {type(e).__name__}: {str(e)[:140]}")
        return None


print("=" * 70)
print("4b. 个股基本信息 替代源")
print("=" * 70)
probe("stock_individual_basic_info_xq(雪球)", ak.stock_individual_basic_info_xq, symbol="SH600519")
probe("stock_profile_cninfo(巨潮)", ak.stock_profile_cninfo, symbol=SYMBOL)
probe("stock_info_a_code_name(全A代码名称)", ak.stock_info_a_code_name)

print("=" * 70)
print("5b. 全市场快照 替代源")
print("=" * 70)
probe("stock_zh_a_spot(新浪全市场)", ak.stock_zh_a_spot)

print("=" * 70)
print("6b. 行业板块 替代源")
print("=" * 70)
probe("stock_board_industry_summary_ths(同花顺行业一览)", ak.stock_board_industry_summary_ths)
probe("stock_board_industry_name_ths(同花顺行业板块)", ak.stock_board_industry_name_ths)
probe("stock_industry_category_cninfo(巨潮行业分类)", ak.stock_industry_category_cninfo, symbol="证监会行业分类标准")

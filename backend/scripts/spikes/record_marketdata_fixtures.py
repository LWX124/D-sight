"""录制 akshare 真实返回为离线测试 fixture。

用法: PYTHONPATH=. .venv/bin/python scripts/spikes/record_marketdata_fixtures.py
接口字段随上游变动时重跑本脚本，diff 即可看出契约变化。
"""

from pathlib import Path

import akshare as ak

from app.core.akshare_runtime import call_akshare

OUT = Path(__file__).resolve().parents[2] / "app" / "marketdata" / "tests" / "fixtures"
SYMBOLS = ["600519", "000001"]


def dump(name: str, df) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"{path.name:48s} shape={df.shape}")


for code in SYMBOLS:
    sina = ("sh" if code.startswith("6") else "sz") + code
    dump(f"daily_{code}", call_akshare(ak.stock_zh_a_daily, symbol=sina, adjust="qfq").tail(400))
    dump(f"value_em_{code}", call_akshare(ak.stock_value_em, symbol=code))
    dump(f"financial_abstract_{code}", call_akshare(ak.stock_financial_abstract, symbol=code))
    dump(f"profile_{code}", call_akshare(ak.stock_profile_cninfo, symbol=code))
    dump(f"fhps_{code}", call_akshare(ak.stock_fhps_detail_em, symbol=code))

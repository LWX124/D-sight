"""一次性校对脚本：抓参考网站估值，与数据库对比并落库。

用法：
    cd backend && python -m scripts.calibrate_ref
"""
import asyncio
import subprocess
import sys

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.fund_arb.job import _REF_PAGES, _parse_ref_page, _upsert_daily
from app.fund_arb.models import FundArbDaily, FundArbFund

WARN_THRESHOLD = 0.5  # %


async def main() -> None:
    ref_data: dict = {}
    for url in _REF_PAGES:
        result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=30)
        ref_data.update(_parse_ref_page(result.stdout))
    if not ref_data:
        print("ERROR: 参考网站解析结果为空", file=sys.stderr)
        sys.exit(1)

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()
        fund_map = {f.sina_symbol.upper(): f for f in funds}

        rows_out = []
        for sym_upper, (ref_est, ref_prem) in sorted(ref_data.items()):
            fund = fund_map.get(sym_upper)
            if fund is None:
                continue
            row = (await db.execute(
                select(FundArbDaily).where(
                    FundArbDaily.fund_code == fund.fund_code,
                    FundArbDaily.est_nav_close.is_not(None),
                ).order_by(FundArbDaily.date.desc()).limit(1)
            )).scalar_one_or_none()

            our_est = row.est_nav_close if row else None
            our_prem = row.premium if row else None
            diff = (our_est / ref_est - 1.0) * 100.0 if our_est else None
            flag = ""
            if diff is not None and abs(diff) > WARN_THRESHOLD:
                flag = " ⚠"
            rows_out.append((sym_upper, our_est, ref_est, diff, our_prem, ref_prem, flag))

            from datetime import date
            await _upsert_daily(db, fund.fund_code, date.today(),
                                ref_est_nav=ref_est, ref_premium=ref_prem)
        await db.commit()

    # 打印报告
    print(f"{'代码':<12} {'我方EST':>8} {'参考EST':>8} {'偏差%':>7} {'我方溢价%':>9} {'参考溢价%':>9}")
    print("-" * 62)
    for sym, our, ref, diff, our_p, ref_p, flag in rows_out:
        our_s = f"{our:.4f}" if our else "  N/A  "
        diff_s = f"{diff:+.2f}%" if diff is not None else "  N/A "
        our_p_s = f"{our_p:+.2f}%" if our_p is not None else "  N/A "
        ref_p_s = f"{ref_p:+.2f}%"
        print(f"{sym:<12} {our_s:>8} {ref:.4f} {diff_s:>7} {our_p_s:>9} {ref_p_s:>9}{flag}")

    warn_count = sum(1 for *_, flag in rows_out if flag)
    print(f"\n共 {len(rows_out)} 只基金，{warn_count} 只偏差超过 {WARN_THRESHOLD}%")


if __name__ == "__main__":
    asyncio.run(main())

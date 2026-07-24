# backend/app/fund_arb/reconciliation.py
import datetime as dt
import logging
import statistics
import subprocess
from dataclasses import dataclass

from sqlalchemy import select

from app.fund_arb.models import FundArbDaily

_log = logging.getLogger(__name__)

_FALLBACK_THRESHOLD = 0.01
_THRESHOLD_WINDOW = 30
_THRESHOLD_SIGMA = 3.0


@dataclass
class ReconcileResult:
    deviation_pct: float
    action: str  # "none" | "corrected"
    corrected_value: float


def reconcile_fund(
    fund_code: str, local_est: float, ref_est: float, threshold: float
) -> ReconcileResult:
    deviation_pct = (local_est / ref_est - 1.0) * 100.0
    if abs(deviation_pct) > threshold * 100.0:
        return ReconcileResult(deviation_pct=deviation_pct, action="corrected", corrected_value=ref_est)
    return ReconcileResult(deviation_pct=deviation_pct, action="none", corrected_value=local_est)


async def compute_dynamic_threshold(fund_code: str, session) -> float:
    rows = (await session.execute(
        select(FundArbDaily.valuation_error)
        .where(
            FundArbDaily.fund_code == fund_code,
            FundArbDaily.valuation_error.is_not(None),
        )
        .order_by(FundArbDaily.date.desc())
        .limit(_THRESHOLD_WINDOW)
    )).scalars().all()
    if len(rows) < 5:
        return _FALLBACK_THRESHOLD
    return statistics.stdev(rows) * _THRESHOLD_SIGMA / 100.0


_REF_PAGES = [
    "https://www.palmmicro.com/woody/res/qdiicn.php",
    "https://www.palmmicro.com/woody/res/chinaindexcn.php",
    "https://www.palmmicro.com/woody/res/chinafuturecn.php",
    "https://www.palmmicro.com/woody/res/qdiimixcn.php",
    "https://www.palmmicro.com/woody/res/qdiihkcn.php",
    "https://www.palmmicro.com/woody/res/qdiieucn.php",
]


def _parse_ref_page(html: str) -> dict[str, tuple[float, float]]:
    import re
    out: dict[str, tuple[float, float]] = {}
    for m in re.finditer(
        r'>([SZ][HZ]\d{6})</a></td>'
        r'<td[^>]*><font[^>]*>([\d.]+)</font></td>'
        r'<td[^>]*>\d{4}-\d{2}-\d{2}</td>'
        r'<td[^>]*><font[^>]*>([-\d.]+)%</font>',
        html,
    ):
        sym, est, prem = m.group(1), float(m.group(2)), float(m.group(3))
        out[sym] = (est, prem)
    return out


async def fetch_ref_nav_all() -> dict[str, tuple[float, float]]:
    ref_data: dict[str, tuple[float, float]] = {}
    for url in _REF_PAGES:
        try:
            result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=30)
            ref_data.update(_parse_ref_page(result.stdout))
        except Exception:
            _log.exception("fund_arb 参考网站抓取失败：%s", url)
    return ref_data


from app.fund_arb.models import FundArbFund, FundArbReconciliation
from app.fund_arb.snapshot import get_store


async def run_reconciliation(session_factory) -> str:
    run_at = dt.datetime.now(dt.timezone.utc)
    ref_data = await fetch_ref_nav_all()
    if not ref_data:
        _log.warning("fund_arb 参考网站解析结果为空，跳过对账")
        return "[reconcile] 参考网站无数据，跳过"

    async with session_factory() as db:
        funds = (await db.execute(
            select(FundArbFund).where(FundArbFund.enabled.is_(True))
        )).scalars().all()

    fund_map = {f.sina_symbol.upper(): f for f in funds}
    lines: list[str] = []
    total = corrected = errors = 0

    for sym_upper, (ref_est, _prem) in ref_data.items():
        fund = fund_map.get(sym_upper)
        if fund is None:
            continue
        total += 1
        try:
            async with session_factory() as db:
                threshold = await compute_dynamic_threshold(fund.fund_code, db)
                snap = get_store()._snaps.get(fund.fund_code)
                local_est = snap.est_nav if snap and snap.est_nav is not None else None
                if local_est is None:
                    continue
                result = reconcile_fund(fund.fund_code, local_est, ref_est, threshold)
                db.add(FundArbReconciliation(
                    fund_code=fund.fund_code,
                    run_at=run_at,
                    local_est_nav=local_est,
                    ref_est_nav=ref_est,
                    deviation_pct=result.deviation_pct,
                    threshold_used=threshold,
                    action=result.action,
                ))
                await db.flush()
                await db.commit()
            if result.action == "corrected":
                get_store().update_est_nav(fund.fund_code, ref_est)
                corrected += 1
            sign = "+" if result.deviation_pct >= 0 else ""
            lines.append(
                f"{fund.fund_code:<8} {local_est:<10.4f} {ref_est:<10.4f} "
                f"{sign}{result.deviation_pct:.2f}%{'':<4} "
                f"{threshold * 100:.2f}%{'':<4} {result.action}"
            )
        except Exception:
            _log.exception("fund_arb 对账失败：%s", fund.fund_code)
            errors += 1

    header = (
        f"[reconcile] {run_at.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}"
        f"  total={total}  corrected={corrected}  errors={errors}"
    )
    col = "fund     local_est  ref_est    deviation  threshold  action"
    summary = "\n".join([header, col] + lines)
    print(summary)
    return summary

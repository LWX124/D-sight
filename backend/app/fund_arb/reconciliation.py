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

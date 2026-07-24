from app.fund_arb.snapshot import SnapshotStore, FundSnapshot
import datetime as dt

def _make_snap(code: str, est: float) -> FundSnapshot:
    return FundSnapshot(
        fund_code=code, fund_name="test", category="qdii_us_eu",
        price=1.0, price_pct=0.0, amount=None,
        est_nav=est, premium=None, nav=est, nav_date=dt.date.today(),
        err_5d=None, low_confidence=False, approx=False,
        purchase_status=None, redemption_status=None, purchase_limit=None,
        as_of=dt.datetime.now(dt.UTC), source="realtime",
    )

def test_update_est_nav():
    store = SnapshotStore()
    store.update([_make_snap("513500", 1.2341)])
    store.update_est_nav("513500", 1.2389)
    assert store._snaps["513500"].est_nav == 1.2389

def test_update_est_nav_missing_code():
    store = SnapshotStore()
    store.update_est_nav("999999", 1.0)  # 不存在时静默忽略


from app.fund_arb.reconciliation import ReconcileResult, reconcile_fund

def test_reconcile_fund_no_action():
    r = reconcile_fund("513500", 1.2341, 1.2350, 0.01)
    assert r.action == "none"
    assert r.corrected_value == 1.2341

def test_reconcile_fund_corrected():
    r = reconcile_fund("513500", 1.2341, 1.2389, 0.003)
    assert r.action == "corrected"
    assert r.corrected_value == 1.2389
    assert abs(r.deviation_pct - (1.2341 / 1.2389 - 1) * 100) < 1e-6

def test_reconcile_fund_negative_deviation():
    r = reconcile_fund("513500", 1.2389, 1.2341, 0.003)
    assert r.action == "corrected"
    assert r.corrected_value == 1.2341


from httpx import ASGITransport, AsyncClient
from app.main import create_app
import pytest

@pytest.mark.anyio
async def test_reconcile_endpoint_forbidden():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/fund-arb/reconcile")
    assert resp.status_code in (401, 403)

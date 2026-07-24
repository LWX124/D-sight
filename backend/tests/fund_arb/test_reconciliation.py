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

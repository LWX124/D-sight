"""Service 层测试。

验证：
1. 正常创建报告并预留积分
2. 活跃任务去重返回原报告，不重复扣费
3. 积分不足抛 InsufficientCredits
4. 幂等键重放返回原报告
5. 幂等键 + fingerprint 不匹配抛 mismatch
6. 管理员免扣费
"""
import uuid

import pytest
from sqlalchemy import select

from app.credits.models import CreditAccount, CreditTransaction
from app.credits.service import InsufficientCredits
from app.deep_analysis.service import (
    IdempotencyFingerprintMismatch,
    _normalize_ticker,
    create_report,
)
from tests.deep_analysis.conftest import _mk_user


@pytest.mark.asyncio
async def test_normalize_ticker():
    assert _normalize_ticker("A", "600519") == "600519.SH"
    assert _normalize_ticker("A", "SH600519") == "600519.SH"
    assert _normalize_ticker("A", "000001") == "000001.SZ"
    assert _normalize_ticker("HK", "700") == "0700.HK"
    assert _normalize_ticker("HK", "00700") == "0700.HK"
    assert _normalize_ticker("US", "aapl") == "AAPL"


@pytest.mark.asyncio
async def test_create_report_basic(db_session):
    u = await _mk_user(db_session, balance=200)
    report, cache_hit, dedup = await create_report(
        db_session, u.id, "A", "600519", idempotency_key=None
    )
    await db_session.commit()
    assert report.status == "pending"
    assert not cache_hit
    assert not dedup
    assert report.reserved_credits == 50
    assert report.credit_state == "reserved"
    acct = await db_session.get(CreditAccount, u.id)
    assert acct.balance == 150


@pytest.mark.asyncio
async def test_active_dedup_returns_original(db_session):
    u = await _mk_user(db_session, balance=200)
    r1, _, _ = await create_report(db_session, u.id, "A", "600519", None)
    await db_session.commit()
    r2, cache_hit, dedup = await create_report(db_session, u.id, "A", "600519", None)
    await db_session.commit()
    assert r1.id == r2.id
    assert dedup
    assert not cache_hit
    acct = await db_session.get(CreditAccount, u.id)
    assert acct.balance == 150  # 只扣一次


@pytest.mark.asyncio
async def test_insufficient_credits(db_session):
    u = await _mk_user(db_session, balance=10)
    with pytest.raises(InsufficientCredits):
        await create_report(db_session, u.id, "A", "000001", None)


@pytest.mark.asyncio
async def test_idempotency_replay(db_session):
    u = await _mk_user(db_session, balance=200)
    key = f"key-{uuid.uuid4().hex[:6]}"
    r1, _, _ = await create_report(db_session, u.id, "A", "600519", key)
    await db_session.commit()
    r2, _, _ = await create_report(db_session, u.id, "A", "600519", key)
    await db_session.commit()
    assert r1.id == r2.id
    acct = await db_session.get(CreditAccount, u.id)
    assert acct.balance == 150  # 只扣一次


@pytest.mark.asyncio
async def test_idempotency_fingerprint_mismatch(db_session):
    u = await _mk_user(db_session, balance=200)
    key = f"key-{uuid.uuid4().hex[:6]}"
    await create_report(db_session, u.id, "A", "600519", key)
    await db_session.commit()
    with pytest.raises(IdempotencyFingerprintMismatch):
        await create_report(db_session, u.id, "US", "AAPL", key)


@pytest.mark.asyncio
async def test_admin_exempt_from_charge(db_session):
    u = await _mk_user(db_session, balance=0, role="admin")
    report, _, _ = await create_report(
        db_session, u.id, "A", "600519", None, is_admin=True
    )
    await db_session.commit()
    assert report.credit_state == "exempt"
    assert report.reserved_credits == 0
    acct = await db_session.get(CreditAccount, u.id)
    assert acct.balance == 0  # 未扣费


@pytest.mark.asyncio
async def test_reserve_writes_credit_transaction_with_operation(db_session):
    """reserve 流水必须带 operation=reserve 且 ref_id 回填为 report_id。"""
    u = await _mk_user(db_session, balance=200)
    report, _, _ = await create_report(db_session, u.id, "A", "600519", None)
    await db_session.commit()
    tx = (
        await db_session.execute(
            select(CreditTransaction).where(
                CreditTransaction.user_id == u.id,
                CreditTransaction.ref_type == "deep_analysis",
                CreditTransaction.operation == "reserve",
            )
        )
    ).scalar_one()
    assert tx.ref_id == str(report.id)
    assert tx.amount == -50

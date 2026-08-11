"""Router 集成测试（通过 ASGITransport）。

验证：
1. POST 创建报告返回 202，含 id/status/reserved_credits
2. GET 单报告返回正确状态
3. GET 他人报告返回 404
4. GET 列表只含当前用户
5. POST 取消 pending 报告，status=cancelled，积分释放
6. DELETE 已取消报告返回 204
7. DELETE 运行中报告返回 409
8. 积分不足返回 402
9. idempotency_key 重放返回同一报告
10. idempotency_key 指纹不匹配返回 409
"""
import uuid

import pytest

from app.core.security import create_access_token
from app.credits.models import CreditAccount
from tests.deep_analysis.conftest import _mk_user



def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _mk_user_with_token(db, balance=200, role="user"):
    u = await _mk_user(db, balance=balance, role=role)
    return u


@pytest.mark.asyncio
async def test_create_returns_202(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    resp = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=_auth(u),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["reserved_credits"] == 50
    assert not data["cache_hit"]
    assert not data["deduplicated"]


@pytest.mark.asyncio
async def test_get_report(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    create_resp = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "000001"},
        headers=_auth(u),
    )
    report_id = create_resp.json()["id"]

    resp = await client.get(f"/api/deep-analysis/{report_id}", headers=_auth(u))
    assert resp.status_code == 200
    assert resp.json()["id"] == report_id
    assert resp.json()["normalized_ticker"] == "000001.SZ"


@pytest.mark.asyncio
async def test_get_other_users_report_404(client, db_session):
    owner = await _mk_user_with_token(db_session, balance=200)
    other = await _mk_user_with_token(db_session, balance=200)

    create_resp = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "300750"},
        headers=_auth(owner),
    )
    report_id = create_resp.json()["id"]

    resp = await client.get(f"/api/deep-analysis/{report_id}", headers=_auth(other))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_pending_releases_credits(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    create_resp = await client.post(
        "/api/deep-analysis",
        json={"market": "US", "ticker": "AAPL"},
        headers=_auth(u),
    )
    report_id = create_resp.json()["id"]

    cancel_resp = await client.post(
        f"/api/deep-analysis/{report_id}/cancel", headers=_auth(u)
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # 积分应被释放回 200
    acct = await db_session.get(CreditAccount, u.id)
    assert acct.balance == 200


@pytest.mark.asyncio
async def test_delete_cancelled_returns_204(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    create_resp = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=_auth(u),
    )
    report_id = create_resp.json()["id"]
    await client.post(f"/api/deep-analysis/{report_id}/cancel", headers=_auth(u))

    resp = await client.delete(f"/api/deep-analysis/{report_id}", headers=_auth(u))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_running_returns_409(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    create_resp = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=_auth(u),
    )
    report_id = create_resp.json()["id"]
    # 未取消直接删（pending 状态属于活跃，应 409）
    resp = await client.delete(f"/api/deep-analysis/{report_id}", headers=_auth(u))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_insufficient_credits_returns_402(client, db_session):
    u = await _mk_user_with_token(db_session, balance=10)
    resp = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=_auth(u),
    )
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_idempotency_replay(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    key = f"key-{uuid.uuid4().hex[:6]}"
    r1 = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519", "idempotency_key": key},
        headers=_auth(u),
    )
    r2 = await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519", "idempotency_key": key},
        headers=_auth(u),
    )
    assert r1.json()["id"] == r2.json()["id"]
    # 积分只扣一次
    acct = await db_session.get(CreditAccount, u.id)
    assert acct.balance == 150


@pytest.mark.asyncio
async def test_idempotency_fingerprint_mismatch_409(client, db_session):
    u = await _mk_user_with_token(db_session, balance=200)
    key = f"key-{uuid.uuid4().hex[:6]}"
    await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519", "idempotency_key": key},
        headers=_auth(u),
    )
    resp = await client.post(
        "/api/deep-analysis",
        json={"market": "US", "ticker": "AAPL", "idempotency_key": key},
        headers=_auth(u),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_only_own_reports(client, db_session):
    u1 = await _mk_user_with_token(db_session, balance=200)
    u2 = await _mk_user_with_token(db_session, balance=200)
    await client.post(
        "/api/deep-analysis",
        json={"market": "A", "ticker": "600519"},
        headers=_auth(u1),
    )
    await client.post(
        "/api/deep-analysis",
        json={"market": "US", "ticker": "AAPL"},
        headers=_auth(u2),
    )

    resp = await client.get("/api/deep-analysis", headers=_auth(u1))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["market"] == "A"

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.credits import service
from tests.test_auth_api import _register


def _auth(user) -> dict:
    """签合法 access token；对注册夹具与直建 User 都用 user.id。"""
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture
async def registered_user(client, db_session):
    # 每个测试独立邮箱：DB 跨用例不回滚，同邮箱二次 request-code 会撞 60s 限流(429)
    email = f"admin-user-{uuid.uuid4().hex[:8]}@test.dev"
    await _register(client, db_session, email)
    row = await db_session.scalar(select(User).where(User.email == email))
    return SimpleNamespace(id=row.id, email=email)


@pytest.mark.asyncio
async def test_non_admin_forbidden(client, db_session, registered_user):
    resp = await client.post(
        "/api/admin/credits/adjust",
        json={"user_id": str(registered_user.id), "delta": 100, "reason": "x"},
        headers=_auth(registered_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_adjust_and_plan(client, db_session):
    admin = User(email=f"a-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin")
    target = User(email=f"u-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([admin, target])
    await db_session.commit()
    await service.ensure_account(db_session, target.id)
    await db_session.commit()

    h = _auth(admin)
    r1 = await client.post(
        "/api/admin/credits/adjust",
        json={"user_id": str(target.id), "delta": 500, "reason": "vip"},
        headers=h,
    )
    assert r1.status_code == 200 and r1.json()["balance"] == 600
    r2 = await client.post(
        f"/api/admin/users/{target.id}/plan", json={"plan": "subscribed"}, headers=h
    )
    assert r2.json()["monthly_quota"] == 2000


@pytest.mark.asyncio
async def test_admin_skill_toggle_and_price(client, db_session):
    from sqlalchemy import select as _select
    from app.credits.models import AdminAuditLog
    from app.skills import seed
    await seed.upsert_skills(db_session)
    await db_session.commit()
    admin = User(email=f"sa-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin")
    db_session.add(admin)
    await db_session.commit()
    h = _auth(admin)
    r = await client.patch("/api/admin/skills/dyp-ask", json={"is_active": False, "price": 5}, headers=h)
    assert r.json() == {"slug": "dyp-ask", "is_active": False, "price": 5}
    audits = (await db_session.execute(
        _select(AdminAuditLog).where(AdminAuditLog.action == "skill_update",
                                     AdminAuditLog.target_id == "dyp-ask")
    )).scalars().all()
    assert audits and audits[-1].detail == {"is_active": False, "price": 5}
    assert (await client.patch("/api/admin/skills/nope", json={"price": 1}, headers=h)).status_code == 404
    assert (await client.patch("/api/admin/skills/dyp-ask", json={"price": -1}, headers=h)).status_code == 400
    # 还原，避免影响其它测试
    await client.patch("/api/admin/skills/dyp-ask", json={"is_active": True, "price": 0}, headers=h)

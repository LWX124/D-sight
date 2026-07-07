import uuid

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.credits import service
from app.credits.models import AdminAuditLog, CreditTransaction

# registered_user / a_thread 由 conftest 提供（自动注入）；helpers 显式导入。
from tests.conftest import _auth, _chat_body


@pytest.mark.asyncio
async def test_precheck_block_then_grant_then_charge(client, db_session, registered_user, a_thread):
    # 扣空余额 → 聊天预检拒绝 402
    await service.charge(db_session, registered_user.id, 1000, kind="adjust")
    await db_session.commit()
    r1 = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r1.status_code == 402

    # 管理员补充积分
    admin = User(
        email=f"adm-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin"
    )
    db_session.add(admin)
    await db_session.commit()
    admin_auth = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}
    r2 = await client.post(
        "/api/admin/credits/adjust",
        json={"user_id": str(registered_user.id), "delta": 50, "reason": "test"},
        headers=admin_auth,
    )
    assert r2.status_code == 200

    # 审计行必须落库（Task 6 review gap：回归丢失审计写入时此断言应失败）
    audits = (
        await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "credit_adjust",
                AdminAuditLog.target_id == str(registered_user.id),
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].detail["delta"] == 50

    # 再次聊天成功且新增 kind="chat" 流水
    r3 = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r3.status_code == 200
    await r3.aread()
    txs = (
        await db_session.execute(
            select(CreditTransaction).where(
                CreditTransaction.user_id == registered_user.id,
                CreditTransaction.kind == "chat",
            )
        )
    ).scalars().all()
    assert len(txs) >= 1

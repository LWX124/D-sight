import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.credits import service
from app.credits.reset import reset_all_accounts


@pytest.mark.asyncio
async def test_reset_zeroes_then_refills_to_quota(db_session):
    u = User(email=f"r-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    acct = await service.ensure_account(db_session, u.id)
    acct.monthly_quota = 2000  # 模拟订阅额度
    await service.charge(db_session, u.id, 90, kind="chat")  # 余额 10
    await db_session.commit()

    n = await reset_all_accounts(db_session)
    assert n >= 1
    assert await service.get_balance(db_session, u.id) == 2000  # 清零再发到配额，非累加

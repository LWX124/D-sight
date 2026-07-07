import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.credits import service
from app.credits.pricing import tokens_to_credits


def test_tokens_to_credits_floor_and_ceil():
    assert tokens_to_credits(0) == 1        # 下限 MIN_CHARGE
    assert tokens_to_credits(1) == 1
    assert tokens_to_credits(1000) == 1
    assert tokens_to_credits(1001) == 2


async def _mk_user(db):
    u = User(email=f"s-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    return u


@pytest.mark.asyncio
async def test_ensure_account_grants_free_quota(db_session):
    u = await _mk_user(db_session)
    acct = await service.ensure_account(db_session, u.id)
    assert acct.balance == 100 and acct.plan == "free"
    # 幂等
    again = await service.ensure_account(db_session, u.id)
    assert again.balance == 100


@pytest.mark.asyncio
async def test_charge_and_precheck(db_session):
    u = await _mk_user(db_session)
    await service.ensure_account(db_session, u.id)
    await service.charge(db_session, u.id, 30, kind="chat", ref_type="thread", ref_id="t1")
    assert await service.get_balance(db_session, u.id) == 70
    await service.precheck(db_session, u.id, need=1)  # 不抛
    await service.charge(db_session, u.id, 100, kind="chat")  # 扣到 0 下限
    assert await service.get_balance(db_session, u.id) == 0
    with pytest.raises(service.InsufficientCredits):
        await service.precheck(db_session, u.id, need=1)

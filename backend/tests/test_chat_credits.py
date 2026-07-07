import pytest

from app.credits import service
from tests.conftest import _auth, _chat_body


@pytest.mark.asyncio
async def test_chat_rejected_when_no_credits(client, db_session, registered_user, a_thread):
    # 把余额扣到 0
    await service.charge(db_session, registered_user.id, 1000, kind="adjust")
    await db_session.commit()
    resp = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_chat_charges_after_run(client, db_session, registered_user, a_thread):
    before = await service.get_balance(db_session, registered_user.id)
    resp = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert resp.status_code == 200
    await resp.aread()  # 消费完整流
    db_session.expire_all()  # 丢弃缓存，重读账户余额
    after = await service.get_balance(db_session, registered_user.id)
    assert after < before  # 至少扣了 MIN_CHARGE

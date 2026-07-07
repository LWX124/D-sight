import uuid

import pytest
from sqlalchemy import func, select

from app.credits import service
from app.credits.models import CreditTransaction
from app.threads.models import Thread
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


@pytest.mark.asyncio
async def test_failed_zero_token_run_not_charged(
    client, db_session, registered_user, a_thread, monkeypatch
):
    """LLM 中途硬失败且 0 token 计量：不得扣费、不得写交易行，但 updated_at 仍推进。"""
    import app.chat.router as router_mod

    async def _count_chat_tx() -> int:
        db_session.expire_all()
        return await db_session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(
                CreditTransaction.user_id == registered_user.id,
                CreditTransaction.kind == "chat",
            )
        )

    before_balance = await service.get_balance(db_session, registered_user.id)
    before_tx = await _count_chat_tx()
    thread = await db_session.get(Thread, uuid.UUID(a_thread))
    before_updated = thread.updated_at

    class _BoomAgent:
        async def astream(self, *args, **kwargs):
            raise RuntimeError("LLM outage before any token")
            yield  # 使之成为 async generator（不可达）

    monkeypatch.setattr(router_mod, "build_agent", lambda *a, **k: _BoomAgent())

    try:
        resp = await client.post(
            "/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user)
        )
        await resp.aread()  # 流内部硬失败，消费/吞掉
    except Exception:
        pass

    db_session.expire_all()
    after_balance = await service.get_balance(db_session, registered_user.id)
    after_tx = await _count_chat_tx()
    after_thread = await db_session.get(Thread, uuid.UUID(a_thread))

    assert after_balance == before_balance  # 0 token 硬失败：无 MIN_CHARGE
    assert after_tx == before_tx  # 无新增 chat 交易行
    assert after_thread.updated_at > before_updated  # updated_at 仍推进

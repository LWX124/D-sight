import uuid

import pytest

from app.auth.models import User
from app.credits.models import CreditAccount, CreditTransaction
from app.core.security import hash_password


@pytest.mark.asyncio
async def test_account_and_transaction_roundtrip(db_session):
    user = User(email=f"c-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(user)
    await db_session.flush()

    acct = CreditAccount(user_id=user.id, balance=100, monthly_quota=100, plan="free")
    db_session.add(acct)
    tx = CreditTransaction(
        user_id=user.id, kind="grant", amount=100, balance_after=100,
        ref_type="signup", ref_id=None,
    )
    db_session.add(tx)
    await db_session.commit()

    got = await db_session.get(CreditAccount, user.id)
    assert got.balance == 100 and got.plan == "free"

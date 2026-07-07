import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credits.models import CreditAccount, CreditTransaction
from app.credits.pricing import quota_for_plan


class InsufficientCredits(Exception):
    pass


async def ensure_account(db: AsyncSession, user_id: uuid.UUID) -> CreditAccount:
    acct = await db.get(CreditAccount, user_id)
    if acct is not None:
        return acct
    quota = quota_for_plan("free")
    acct = CreditAccount(user_id=user_id, balance=quota, monthly_quota=quota, plan="free")
    db.add(acct)
    db.add(CreditTransaction(
        user_id=user_id, kind="grant", amount=quota, balance_after=quota,
        ref_type="signup", ref_id=None,
    ))
    await db.flush()
    return acct


async def get_balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    acct = await db.get(CreditAccount, user_id)
    return acct.balance if acct else 0


async def precheck(db: AsyncSession, user_id: uuid.UUID, need: int) -> None:
    if await get_balance(db, user_id) < need:
        raise InsufficientCredits()


async def _apply(db, user_id, delta, kind, ref_type, ref_id) -> CreditTransaction:
    # 行锁读账户，防并发双扣（SELECT ... FOR UPDATE）
    acct = (
        await db.execute(
            select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if acct is None:
        acct = await ensure_account(db, user_id)
        acct = (
            await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update()
            )
        ).scalar_one()
    acct.balance = max(0, acct.balance + delta)
    tx = CreditTransaction(
        user_id=user_id, kind=kind, amount=delta, balance_after=acct.balance,
        ref_type=ref_type, ref_id=ref_id,
    )
    db.add(tx)
    await db.flush()
    return tx


async def charge(db, user_id, amount, kind, ref_type=None, ref_id=None) -> CreditTransaction:
    return await _apply(db, user_id, -abs(amount), kind, ref_type, ref_id)


async def grant(db, user_id, amount, kind, ref_type=None, ref_id=None) -> CreditTransaction:
    return await _apply(db, user_id, abs(amount), kind, ref_type, ref_id)

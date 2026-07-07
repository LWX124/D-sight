import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credits.models import CreditAccount, CreditTransaction


async def reset_all_accounts(db: AsyncSession) -> int:
    accts = (await db.execute(select(CreditAccount).with_for_update())).scalars().all()
    now = dt.datetime.now(dt.UTC)
    for a in accts:
        delta = a.monthly_quota - a.balance  # 清零再发：直接置为配额，流水记差额
        a.balance = a.monthly_quota
        a.reset_at = now
        db.add(CreditTransaction(
            user_id=a.user_id, kind="reset", amount=delta, balance_after=a.balance,
            ref_type="monthly", ref_id=now.strftime("%Y-%m"),
        ))
    await db.commit()
    return len(accts)

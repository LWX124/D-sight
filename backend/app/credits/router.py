from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.credits import service
from app.core.db import get_db

router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.get("")
async def get_credits(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    acct = await service.ensure_account(db, user.id)
    await db.commit()
    return {"balance": acct.balance, "monthly_quota": acct.monthly_quota, "plan": acct.plan}

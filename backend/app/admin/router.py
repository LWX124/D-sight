import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import require_admin
from app.admin.schemas import CreditAdjust, PlanChange
from app.auth.models import User
from app.core.db import get_db
from app.credits import service
from app.credits.models import AdminAuditLog
from app.credits.pricing import quota_for_plan

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/credits/adjust")
async def adjust_credits(
    body: CreditAdjust, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    try:
        uid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(400, "非法用户ID")
    await service.ensure_account(db, uid)
    if body.delta >= 0:
        await service.grant(db, uid, body.delta, kind="adjust", ref_type="admin", ref_id=str(admin.id))
    else:
        await service.charge(db, uid, -body.delta, kind="adjust", ref_type="admin", ref_id=str(admin.id))
    db.add(AdminAuditLog(
        admin_id=admin.id, action="credit_adjust", target_type="user", target_id=body.user_id,
        detail={"delta": body.delta, "reason": body.reason},
    ))
    await db.commit()
    return {"balance": await service.get_balance(db, uid)}


@router.post("/users/{user_id}/plan")
async def change_plan(
    user_id: str, body: PlanChange, admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.plan not in ("free", "subscribed"):
        raise HTTPException(400, "非法套餐")
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "非法用户ID")
    acct = await service.ensure_account(db, uid)
    acct.plan = body.plan
    acct.monthly_quota = quota_for_plan(body.plan)
    db.add(AdminAuditLog(
        admin_id=admin.id, action="plan_change", target_type="user", target_id=user_id,
        detail={"plan": body.plan},
    ))
    await db.commit()
    return {"plan": acct.plan, "monthly_quota": acct.monthly_quota}
